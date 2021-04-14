# SPDX-License-Identifier: AGPL-3.0-or-later
import codecs

import falcon
import kopano

from grapi.api.v1.resource import HTTPConflict
from MAPI.Struct import MAPIErrorCollision

from .resource import DEFAULT_TOP, Resource
from .utils import _folder, _server_store, db_get, db_put, experimental
from .schema import folder_schema, destination_id_schema

from kopano import Restriction
from MAPI import RELOP_EQ
from MAPI.Struct import (SPropertyRestriction, MAPIErrorInvalidEntryid, SPropValue)
from MAPI.Tags import PR_CONTAINER_CLASS_W


class DeletedFolder(object):
    pass


class FolderImporter:
    def __init__(self):
        self.updates = []
        self.deletes = []

    def update(self, folder):
        self.updates.append(folder)
        db_put(folder.sourcekey, folder.entryid)  # TODO different db?

    def delete(self, folder, flags):
        d = DeletedFolder()
        d.entryid = db_get(folder.sourcekey)
        d.container_class = 'IPF.Note'  # TODO
        self.deletes.append(d)


class FolderResource(Resource):
    fields = {
        'id': lambda folder: folder.entryid,
    }

    def __init__(self, options):
        super().__init__(options)

    container_classes = None
    container_class = None

    @experimental
    def handle_delete(self, req, resp, store, folder):
        store.delete(folder)
        self.respond_204(resp)

    # Some folder do not have any method to get them. In that case it is possible
    # to get that folders by enabling restrictions. This will collect all folders
    # with the container_class of this resource
    needs_restriction = False

    @classmethod
    def default_folders_list(cls, store):
        return store.folders

    @classmethod
    def get_all(cls, req, resp, store, server, userid):
        restriction = None
        if cls.needs_restriction:
            restriction = Restriction(SPropertyRestriction(
                RELOP_EQ, PR_CONTAINER_CLASS_W,
                SPropValue(PR_CONTAINER_CLASS_W, cls.container_class)
            ))

        data = cls.generator(req, cls.default_folders_list(store), 0, restriction)
        cls.respond(req, resp, data, cls.fields)

    @classmethod
    def name_field(cls, fields: dict):
        return fields['displayName']

    validation_schema = folder_schema

    @classmethod
    def get(cls, req, resp, store, folderid):
        if folderid == 'delta':
            cls._get_delta(req, resp, store=store)
        else:
            cls._get_by_id(req, resp, store=store, folderid=folderid)

    @classmethod
    def _get_delta(cls, req, resp, store):
        req.context.deltaid = '{folderid}'
        cls.delta(req, resp, store=store)

    @classmethod
    def _get_by_id(cls, req, resp, store, folderid):
        folder = cls.get_folder_by_id(store, folderid)
        if not folder:
            raise falcon.HTTPNotFound(description="Folder not found")
        cls.respond(req, resp, folder, cls.fields)

    @classmethod
    def get_children(cls, req, resp, store, folderid):
        folder = cls.get_folder_by_id(store, folderid)
        children = cls.generator(req, folder.folders, folder.subfolder_count_recursive)
        cls.respond(req, resp, children)

    @classmethod
    def create(cls, req, resp, store):
        fields = cls.load_json(req)
        cls.validate_json(cls.validation_schema, fields)
        try:
            folder = store.create_folder(cls.name_field(fields))
            folder.container_class = cls.container_class
        except kopano.errors.DuplicateError:
            raise HTTPConflict("'%s' folder already exists" % fields['displayName'])
        resp.status = falcon.HTTP_201
        cls.respond(req, resp, folder, cls.fields)

    @classmethod
    def create_child(cls, req, resp, store, folderid):
        folder = cls.get_folder_by_id(store, folderid)
        cls.create(req, resp, folder)

    @classmethod
    def copy(cls, req, resp, store, folderid):
        cls._copy_or_move(req, resp, store, folderid, move=False)

    @classmethod
    def move(cls, req, resp, store, folderid):
        cls._copy_or_move(req, resp, store, folderid, move=True)

    @classmethod
    def _copy_or_move(cls, req, resp, store, folderid, move=False):
        """Handle POST request for Copy or Move actions."""
        folder = cls.get_folder_by_id(store, folderid)
        fields = cls.load_json(req)
        cls.validate_json(destination_id_schema, fields)
        if not folder:
            raise falcon.HTTPNotFound(description="source folder not found")

        to_folder = store.folder(entryid=fields['destinationId'].encode('ascii'))  # TODO ascii?
        if not to_folder:
            raise falcon.HTTPNotFound(description="destination folder not found")

        if move:
            try:
                folder.parent.move(folder, to_folder)
            except MAPIErrorCollision:
                raise HTTPConflict("move has failed because some items already exists")
        else:
            try:
                folder.parent.copy(folder, to_folder)
            except MAPIErrorCollision:
                raise HTTPConflict("copy has failed because some items already exists")

        new_folder = to_folder.folder(folder.name)
        cls.respond(req, resp, new_folder, cls.fields)

    def on_delete(self, req, resp, userid=None, folderid=None, method=None):
        server, store, userid = _server_store(req, userid, self.options)
        folder = _folder(store, folderid)

        if not folder:
            raise falcon.HTTPNotFound(description="folder not found")

        self.handle_delete(req, resp, store=store, folder=folder)

    @experimental
    def delta(self, req, resp, store):  # TODO contactfolders, calendars.. use restriction?
        args = self.parse_qs(req)
        token = args['$deltatoken'][0] if '$deltatoken' in args else None
        importer = FolderImporter()
        newstate = store.subtree.sync_hierarchy(importer, token)
        changes = [(o, self) for o in importer.updates] + \
                  [(o, self.deleted_resource) for o in importer.deletes]
        changes = [c for c in changes if c[0].container_class in self.container_classes]  # TODO restriction?
        data = (changes, DEFAULT_TOP, 0, len(changes))
        deltalink = b"%s?$deltatoken=%s" % (req.path.encode('utf-8'), codecs.encode(newstate, 'ascii'))

        self.respond(req, resp, data, self.fields, deltalink=deltalink)
