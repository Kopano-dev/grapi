# SPDX-License-Identifier: AGPL-3.0-or-later
from .folder import FolderResource
from .task import TaskResource
from .utils import HTTPBadRequest, _server_store, experimental


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

    def on_get(self, req, resp, userid=None, folderid=None, method=None):
        if not method:
            handler = self.get

        elif method == 'childFolders':
            handler = self.get_children

        elif method == 'notes':
            handler = TaskResource.get_all_from_folder

        else:
            raise HTTPBadRequest("Unsupported todolist segment '%s'" % method)

        server, store, userid = _server_store(req, userid, self.options)
        handler(req, resp, store=store, folderid=folderid)

    def on_post(self, req, resp, userid=None, folderid=None, method=None):
        if method == 'tasks':
            handler = TaskResource.create_in_folder

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
        handler(req, resp, store=store, folderid=folderid)
