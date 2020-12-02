# SPDX-License-Identifier: AGPL-3.0-or-later
from .contact import ContactResource
from .folder import FolderResource
from .utils import HTTPBadRequest, _server_store, experimental


class DeletedContactFolderResource(FolderResource):
    fields = {
        '@odata.type': lambda folder: '#microsoft.graph.contactFolder',  # TODO
        'id': lambda folder: folder.entryid,
        '@removed': lambda folder: {'reason': 'deleted'}  # TODO soft deletes
    }


@experimental
class ContactFolderResource(FolderResource):
    @classmethod
    def default_folders_list(cls, store):
        return store.contact_folders

    fields = FolderResource.fields.copy()
    fields.update({
        'displayName': lambda folder: folder.name,
        'parentFolderId': lambda folder: folder.parent.entryid,
    })

    deleted_resource = DeletedContactFolderResource
    container_classes = ('IPF.Contact',)
    container_class = 'IPF.Contact'

    def handle_get_delta(self, req, resp, store, folderid):
        req.context.deltaid = '{folderid}'
        self.delta(req, resp, store)

    def on_get(self, req, resp, userid=None, folderid=None, method=None):
        if folderid == 'delta':
            handler = self.handle_get_delta
        else:
            if not method:
                handler = self.get

            elif method == 'contacts':
                handler = ContactResource.get_all_from_folder

            elif method == 'childFolders':
                handler = self.get_children

            elif method:
                raise HTTPBadRequest("Unsupported contactfolder segment '%s'" % method)

            else:
                raise HTTPBadRequest("Unsupported in contactfolder")

        server, store, userid = _server_store(req, userid, self.options)
        handler(req, resp, store=store, folderid=folderid)

    def on_post(self, req, resp, userid=None, folderid=None, method=None):
        if method == 'contacts':
            handler = ContactResource.create_in_folder

        elif method == 'childFolders':
            handler = self.create_child

        elif method == 'copy':
            handler = self.copy

        elif method == 'move':
            handler = self.move

        elif method:
            raise HTTPBadRequest("Unsupported contactfolder segment '%s'" % method)

        else:
            raise HTTPBadRequest("Unsupported in contactfolder")

        server, store, userid = _server_store(req, userid, self.options)
        handler(req, resp, store=store, folderid=folderid)
