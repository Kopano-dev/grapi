# SPDX-License-Identifier: AGPL-3.0-or-later

from .folder import FolderResource
from .task import TaskResource
from .utils import HTTPBadRequest, _folder, _server_store, experimental


class DeletedTodoListResource(FolderResource):
    fields = {
        '@odata.type': lambda folder: '#microsoft.graph.todoTaskList',  # TODO
        'id': lambda folder: folder.entryid,
        '@removed': lambda folder: {'reason': 'deleted'}  # TODO soft deletes
    }


@experimental
class TodoListResource(FolderResource):
    needs_restriction = True

    fields = FolderResource.fields.copy()
    fields.update({
        'parentFolderId': lambda folder: folder.parent.entryid,
        'displayName': lambda folder: folder.name,
        'unreadItemCount': lambda folder: folder.unread,
        'totalItemCount': lambda folder: folder.count,
        'childFolderCount': lambda folder: folder.subfolder_count,
    })

    deleted_resource = DeletedTodoListResource
    container_classes = (None, 'IPF.Task')
    container_class = 'IPF.Task'

    def handle_get_childFolders(self, req, resp, store, folderid):
        data = _folder(store, folderid)

        data = self.generator(req, data.folders, data.subfolder_count_recursive)
        self.respond(req, resp, data)

    def handle_get_notes(self, req, resp, store, folderid):
        data = _folder(store, folderid)

        data = self.folder_gen(req, data)
        self.respond(req, resp, data, TaskResource.fields)

    def handle_get(self, req, resp, store, folderid):
        if folderid:
            if folderid == 'delta':
                self._handle_get_delta(req, resp, store=store)
            else:
                self._handle_get_with_folderid(req, resp, store=store, folderid=folderid)

    def _handle_get_delta(self, req, resp, store):
        req.context.deltaid = '{folderid}'
        self.delta(req, resp, store=store)

    def _handle_get_with_folderid(self, req, resp, store, folderid):
        data = _folder(store, folderid)
        self.respond(req, resp, data)

    def on_get(self, req, resp, userid=None, folderid=None, method=None):
        handler = None

        if not method:
            handler = self.handle_get

        elif method == 'childFolders':
            handler = self.handle_get_childFolders

        elif method == 'notes':
            handler = self.handle_get_notes

        else:
            raise HTTPBadRequest("Unsupported notebook segment '%s'" % method)

        server, store, userid = _server_store(req, userid, self.options)
        handler(req, resp, store=store, folderid=folderid)

    def handle_post_tasks(self, req, resp, store, folderid):
        folder = _folder(store, folderid)
        fields = self.load_json(req)
        item = self.create_item(folder, fields, TaskResource.set_fields)
        self.respond(req, resp, item, TaskResource.fields)

    def on_post(self, req, resp, userid=None, folderid=None, method=None):
        handler = None

        if method == 'tasks':
            handler = self.handle_post_tasks

        elif method == 'childFolders':
            handler = self.create_child

        elif method == 'copy':
            handler = self.copy

        elif method == 'move':
            handler = self.move

        elif method:
            raise HTTPBadRequest("Unsupported notebook segment '%s'" % method)

        else:
            raise HTTPBadRequest("Unsupported in notebook")

        server, store, userid = _server_store(req, userid, self.options)
        handler(req, resp, store, folderid)
