# SPDX-License-Identifier: AGPL-3.0-or-later
from grapi.api.v1.resource import HTTPBadRequest
from .folder import FolderResource
from .message import MessageResource
from .utils import _server_store, experimental


class DeletedMailFolderResource(FolderResource):
    fields = {
        '@odata.type': lambda folder: '#microsoft.graph.mailFolder',  # TODO
        'id': lambda folder: folder.entryid,
        '@removed': lambda folder: {'reason': 'deleted'}  # TODO soft deletes
    }


@experimental
class MailFolderResource(FolderResource):
    @classmethod
    def default_folders_list(cls, store):
        return store.mail_folders

    fields = FolderResource.fields.copy()
    fields.update({
        'parentFolderId': lambda folder: folder.parent.entryid,
        'displayName': lambda folder: folder.name,
        'unreadItemCount': lambda folder: folder.unread,
        'totalItemCount': lambda folder: folder.count,
        'childFolderCount': lambda folder: folder.subfolder_count,
    })

    relations = {
        'childFolders': lambda folder: (folder.folders, MailFolderResource),
        'messages': lambda folder: (folder.items, MessageResource)  # TODO event msgs
    }

    deleted_resource = DeletedMailFolderResource
    container_classes = (None, 'IPF.Note')
    container_class = 'IPF.Note'

    def on_get(self, req, resp, userid=None, folderid=None, method=None):
        if method is None:
            handler = self.get
        elif method == "childFolders":
            handler = self.get_children
        elif method == "messages":
            handler = MessageResource.get_all_from_folder
        else:
            raise HTTPBadRequest("Unsupported mailFolder segment '%s'" % method)

        server, store, userid = _server_store(req, userid, self.options)
        handler(req, resp, store=store, folderid=folderid)

    def on_post(self, req, resp, userid=None, folderid=None, method=None):
        if method == 'messages':
            handler = MessageResource.create_in_folder

        elif method == 'childFolders':
            handler = self.create_child

        elif method == 'copy':
            handler = self.copy

        elif method == 'move':
            handler = self.move

        elif method:
            raise HTTPBadRequest("Unsupported mailFolder segment '%s'" % method)

        else:
            raise HTTPBadRequest("Unsupported in mailfolder")

        server, store, userid = _server_store(req, userid, self.options)
        handler(req, resp, store=store, folderid=folderid)
