# SPDX-License-Identifier: AGPL-3.0-or-later
import base64
import falcon
import logging

import kopano
import calendar
import codecs
import datetime

import dateutil

from . import attachment
from .resource import DEFAULT_TOP, Resource, _date
from .utils import db_get, db_put, experimental, _item, HTTPBadRequest, _folder


def get_body(req, item):
    prefer_body_content_type = req.context.prefer.get('outlook.body-content-type')

    if prefer_body_content_type == 'text':
        return {'contentType': 'text', 'content': item.text}
    else:
        return {'contentType': 'html', 'content': codecs.decode(item.html_utf8, 'utf-8')}  # TODO can we use bytes to avoid recoding?


def set_body(item, arg):
    if arg['contentType'] == 'text':
        item.text = arg['content']
    elif arg['contentType'] == 'html':
        item.html = arg['content'].encode('utf8')


def get_email(addr):
    return {'emailAddress': {'name': addr.name, 'address': addr.email}}


class DeletedItem(object):
    pass


class ItemImporter:
    def __init__(self):
        self.updates = []
        self.deletes = []

    def update(self, item, flags):
        self.updates.append(item)
        db_put(item.sourcekey, item.entryid)

    def delete(self, item, flags):
        d = DeletedItem()
        d.entryid = db_get(item.sourcekey)
        self.deletes.append(d)


class ItemResource(Resource):
    fields = {
        '@odata.etag': lambda item: 'W/"'+item.changekey+'"',
        'id': lambda item: item.entryid,
        'changeKey': lambda item: item.changekey,
        'createdDateTime': lambda item: _date(item.created),
        'lastModifiedDateTime': lambda item: _date(item.last_modified),
        'categories': lambda item: item.categories,
    }
    set_fields = None
    message_class = None
    validation_schema = None

    # This method needs to be overridden by all item resources
    def __init__(self, options):
        super().__init__(options)
        self.deleted_resource = None

    # This may be overridden in case any custom operations need to be done on the item
    # after it has been created
    @classmethod
    def do_custom(cls, item, fields: dict):
        pass

    # This may be overridden in case the default folder to get items differs from the
    # default create folder
    @classmethod
    def default_folder_get_all(cls, store):
        return _folder(store, cls.default_folder_id)

    @classmethod
    def get_item_by_id(cls, folder, itemid):
        if not itemid:
            raise HTTPBadRequest("Missing itemId. Cannot get %s" % cls.message_class)
        return _item(folder, itemid)

    @classmethod
    def get(cls, req, resp, store, folderid, itemid):
        folder = cls.get_folder_by_id(store, folderid)
        if itemid == 'delta':
            cls._get_delta(req, resp, folder=folder)
        else:
            cls._get_item_id(req, resp, folder=folder, itemid=itemid)

    @classmethod
    def _get_delta(cls, req, resp, folder):
        req.context.deltaid = '{itemid}'
        cls.delta(req, resp, folder=folder)

    @classmethod
    def _get_item_id(cls, req, resp, folder, itemid):
        item = cls.get_item_by_id(folder, itemid)
        cls.respond(req, resp, item)

    @classmethod
    def get_all(cls, req, resp, store, server=None, userid=None):
        cls.get_all_from_folder(req, resp, store, cls.default_folder_id)

    @classmethod
    def get_all_from_folder(cls, req, resp, store, folderid):
        folder = cls.get_folder_by_id(store, folderid)
        data = cls.folder_gen(req, folder)
        cls.respond(req, resp, data, cls.fields)

    @classmethod
    def get_attachments(cls, req, resp, store, folderid, itemid):
        folder = cls.get_folder_by_id(store, folderid)
        item = cls.get_item_by_id(folder, itemid)
        attachments = list(attachment.get_attachments(item))
        data = (attachments, DEFAULT_TOP, 0, len(attachments))
        cls.respond(req, resp, data)

    @classmethod
    def add_attachments(cls, req, resp, store, folderid, itemid):
        folder = cls.get_folder_by_id(store, folderid)
        item = cls.get_item_by_id(folder, itemid)
        fields = cls.load_json(req)
        odataType = fields.get('@odata.type', None)
        if odataType == '#microsoft.graph.fileAttachment':  # TODO other types
            att = item.create_attachment(fields['name'], base64.urlsafe_b64decode(fields['contentBytes']))
            cls.respond(req, resp, att, attachment.AttachmentResource.fields)
            resp.status = falcon.HTTP_201
        else:
            raise HTTPBadRequest("Unsupported attachment @odata.type: '%s'" % odataType)

    @classmethod
    def copy(cls, req, resp, store, folderid, itemid):
        cls._copy_or_move(req, resp, store=store, folderid=folderid, itemid=itemid)

    @classmethod
    def move(cls, req, resp, store, folderid, itemid):
        cls._copy_or_move(req, resp, store=store, folderid=folderid, itemid=itemid, move=True)

    @classmethod
    def _copy_or_move(cls, req, resp, store, folderid, itemid, move=False):
        folder = cls.get_folder_by_id(store, folderid)
        item = cls.get_item_by_id(folder, itemid)
        fields = cls.load_json(req)
        to_folder = store.folder(entryid=fields['destinationId'].encode('ascii'))  # TODO ascii?
        if move:
            item = item.move(to_folder)
        else:
            item = item.copy(to_folder)

    @classmethod
    def create(cls, req, resp, store):
        if cls.alt_folder_id:
            folder = cls.alt_folder_id
        else:
            folder = cls.default_folder_id
        cls.create_in_folder(req, resp, store, folder)

    @classmethod
    def create_in_folder(cls, req, resp, store, folderid):
        folder = cls.get_folder_by_id(store, folderid)
        fields = cls.load_json(req)
        if cls.validation_schema:
            cls.validate_json(cls.validation_schema, fields)
        try:
            item = cls.create_item(folder, fields, cls.set_fields)
        except kopano.errors.ArgumentError as e:
            raise HTTPBadRequest("Invalid argument error '{}'".format(e))
        if cls.message_class:
            item.message_class = cls.message_class
        else:
            logging.warning("No message_class defined for item: %s" % cls.__class__.__name__)
        cls.do_custom(item, fields)
        resp.status = falcon.HTTP_201
        cls.respond(req, resp, item, cls.fields)

    @classmethod
    def patch(cls, req, resp, store, folderid, itemid):
        folder = cls.get_folder_by_id(store, folderid)
        item = cls.get_item_by_id(folder, itemid)
        fields = cls.load_json(req)

        for field, value in fields.items():
            if field in cls.set_fields:
                cls.set_fields[field](item, value)

        cls.do_custom(item, fields)
        cls.respond(req, resp, item, cls.fields)

    @classmethod
    def do_custom_before_delete(cls, item):
        pass

    @classmethod
    def delete(cls, req, resp, store, folderid, itemid):
        if folderid:
            folder = _folder(store, folderid)
        else:
            folder = store
        item = cls.get_item_by_id(folder, itemid)
        cls.do_custom_before_delete(item)
        store.delete(item)
        cls.respond_204(resp)

    @experimental
    def delta(self, req, resp, folder):
        args = self.parse_qs(req)
        token = args['$deltatoken'][0] if '$deltatoken' in args else None
        filter_ = args['$filter'][0] if '$filter' in args else None
        begin = None
        if filter_ and filter_.startswith('receivedDateTime ge '):
            begin = dateutil.parser.parse(filter_[20:])
            seconds = calendar.timegm(begin.timetuple())
            begin = datetime.datetime.utcfromtimestamp(seconds)
        importer = ItemImporter()
        newstate = folder.sync(importer, token, begin=begin)
        changes = [(o, self) for o in importer.updates] + \
            [(o, self.deleted_resource) for o in importer.deletes]
        data = (changes, DEFAULT_TOP, 0, len(changes))
        # TODO include filter in token?
        deltalink = b"%s?$deltatoken=%s" % (req.path.encode('utf-8'), codecs.encode(newstate, 'ascii'))
        self.respond(req, resp, data, self.fields, deltalink=deltalink)
