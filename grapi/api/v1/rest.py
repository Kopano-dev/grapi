# SPDX-License-Identifier: AGPL-3.0-or-later
import logging

import falcon

from .api import API, APIResource
from .batch import BatchResource
from .config import PREFIX
from .healthcheck import HealthCheckResource
from .prefer import Prefer
from .request import Request
from .timezone import to_timezone


class BackendMiddleware:
    def __init__(self, name_backend, default_backend, options):
        self.name_backend = name_backend
        self.default_backend = default_backend
        self.options = options

    def process_resource(self, req, resp, resource, params):
        if not isinstance(resource, BackendResource):
            return

        prefer = req.context.prefer = Prefer(req)

        # Common request validaton.
        prefer_timeZone = prefer.get('outlook.timezone', raw=True)
        if prefer_timeZone:
            try:
                prefer_tzinfo = to_timezone(prefer_timeZone)
            except Exception:
                logging.debug('unsupported timezone value received in request: %s', prefer_timeZone)
                raise falcon.HTTPBadRequest(description="Provided prefer timezone value is not supported.")
            prefer.update('outlook.timezone', (prefer_tzinfo, prefer_timeZone))

        # Backend selection.

        backend = None

        # userid prefixed with backend name, e.g. imap.userid
        userid = params.get('userid')
        if userid:
            # TODO handle unknown backend
            for name in self.name_backend:
                if userid.startswith(name+'.'):
                    backend = self.name_backend[name]
                    params['userid'] = userid[len(name)+1:]
                    break

        # userresource method determines backend type # TODO solve nicer in routing? (fight the falcon)
        method = params.get('method')
        if method and not backend and resource.name == 'UserResource':
            if method in (
                'messages',
                'mailFolders'
            ):
                backend = self.default_backend.get('mail')
            elif method in (
                'contacts',
                'contactFolders',
                'memberOf',
                'photos'
            ):
                backend = self.default_backend.get('directory')
            elif method in (
                'notebooks',
                'notes'
            ):
                backend = self.default_backend.get('note')
            elif method in (
                'tasks',
                'todolists'
            ):
                backend = self.default_backend.get('task')
            else:
                backend = self.default_backend.get('calendar')

        # fall back to default backend for type
        if not backend:
            backend = resource.default_backend

        # result: eg ldap.UserResource() or kopano.MessageResource()
        req.context.resource = getattr(backend, resource.name)(self.options)


class BackendResource(APIResource):
    def __init__(self, default_backend, resource_name):
        super().__init__(resource=None)

        self.default_backend = default_backend
        self.name = resource_name

    def getResource(self, req):
        # Resource is per request, injected by BackendMiddleware.
        return req.context.resource


class RestAPI(API):
    def __init__(self, options=None, middleware=None, backends=None):
        if backends is None:
            backends = ['kopano']

        name_backend = {}
        for name in backends:
            backend = self.import_backend(name, options)
            name_backend[name] = backend

        # TODO(jelle): make backends define their types by introducting a constant in grapi.api
        # And specifying it in backends.
        backend_types = {
            'ldap': ['directory'],
            'kopano': ['directory', 'mail', 'calendar', 'note', 'todo'],
            'imap': ['mail'],
            'caldav': ['calendar'],
            'mock': ['mail', 'directory'],
        }

        default_backend = {}
        for type_ in ('directory', 'mail', 'calendar', 'note', 'todo'):
            for name, types in backend_types.items():
                if name in backends and type_ in types:
                    default_backend[type_] = name_backend[name]  # TODO type occurs twice

        middleware = (middleware or []) + [BackendMiddleware(name_backend, default_backend, options)]
        super().__init__(media_type=None, request_type=Request, middleware=middleware)

        self.req_options.strip_url_path_trailing_slash = True

        self.add_routes(default_backend, options)

    def route(self, path, resource, method=True):
        self.add_route(path, resource)
        if method:  # TODO make optional in a better way?
            self.add_route(path+'/{method}', resource)

    def add_routes(self, default_backend, options):
        healthCheck = HealthCheckResource()
        self.add_route('/health-check', healthCheck)

        batchEndpoint = BatchResource(None, self)
        self.add_route(PREFIX + '/$batch', batchEndpoint)

        directory = default_backend.get('directory')
        if directory:
            users = BackendResource(directory, 'UserResource')
            groups = BackendResource(directory, 'GroupResource')
            contactfolders = BackendResource(directory, 'ContactFolderResource')
            contacts = BackendResource(directory, 'ContactResource')
            photos = BackendResource(directory, 'ProfilePhotoResource')

            self.route(PREFIX+'/me', users)
            self.route(PREFIX+'/users', users, method=False)  # TODO method == ugly
            self.route(PREFIX+'/users/{userid}', users)
            self.route(PREFIX+'/groups', groups, method=False)
            self.route(PREFIX+'/groups/{groupid}', groups)

            for user in (PREFIX+'/me', PREFIX+'/users/{userid}'):
                self.route(user+'/contactFolders/{folderid}', contactfolders)
                self.route(user+'/contacts/{itemid}', contacts)
                self.route(user+'/contactFolders/{folderid}/contacts/{itemid}', contacts)
                self.route(user+'/photo', photos)
                self.route(user+'/photos/{photoid}', photos)
                self.route(user+'/contacts/{itemid}/photo', photos)
                self.route(user+'/contacts/{itemid}/photos/{photoid}', photos)
                self.route(user+'/contactFolders/{folderid}/contacts/{itemid}/photo', photos)
                self.route(user+'/contactFolders/{folderid}/contacts/{itemid}/photos/{photoid}', photos)

        mail = default_backend.get('mail')
        if mail:
            messages = BackendResource(mail, 'MessageResource')
            attachments = BackendResource(mail, 'AttachmentResource')
            mailfolders = BackendResource(mail, 'MailFolderResource')

            for user in (PREFIX+'/me', PREFIX+'/users/{userid}'):
                self.route(user+'/mailFolders/{folderid}', mailfolders)
                self.route(user+'/messages/{itemid}', messages)
                self.route(user+'/mailFolders/{folderid}/messages/{itemid}', messages)
                self.route(user+'/messages/{itemid}/attachments/{attachmentid}', attachments)
                self.route(user+'/mailFolders/{folderid}/messages/{itemid}/attachments/{attachmentid}', attachments)

        calendar = default_backend.get('calendar')
        if calendar:
            calendars = BackendResource(calendar, 'CalendarResource')
            events = BackendResource(calendar, 'EventResource')
            calendar_attachments = BackendResource(calendar, 'AttachmentResource')

            for user in (PREFIX+'/me', PREFIX+'/users/{userid}'):
                self.route(user+'/calendar', calendars)
                self.route(user+'/calendars/{folderid}', calendars)
                self.route(user+'/events/{eventid}', events)
                self.route(user+'/calendar/events/{eventid}', events)
                self.route(user+'/calendars/{folderid}/events/{eventid}', events)
                self.route(user+'/events/{eventid}/attachments/{attachmentid}', calendar_attachments)  # TODO other routes
                self.route(user+'/calendar/events/{eventid}/attachments/{attachmentid}', calendar_attachments)
                self.route(user+'/calendars/{folderid}/events/{eventid}/attachments/{attachmentid}', calendar_attachments)

        note = default_backend.get('note')
        if note:
            notes = BackendResource(note, 'NoteResource')
            note_attachment = BackendResource(note, 'AttachmentResource')
            notebooks = BackendResource(note, 'NotebookResource')

            for user in (PREFIX+'/me', PREFIX+'/users/{userid}'):
                self.route(user+'/notebooks/{folderid}', notebooks)
                self.route(user+'/notes/{itemid}', notes)
                self.route(user+'/notebooks/{folderid}/notes/{itemid}', notes)
                self.route(user+'/notes/{itemid}/attachments/{attachmentid}', note_attachment)
                self.route(user+'/notebooks/{folderid}/notes/{itemid}/attachments/{attachmentid}', note_attachment)

        todo = default_backend.get('todo')
        if todo:
            tasks = BackendResource(todo, 'TaskResource')
            todo_attachment = BackendResource(todo, 'AttachmentResource')
            todo_lists = BackendResource(todo, 'TodoListResource')

            for user in (PREFIX+'/me', PREFIX+'/users/{userid}'):
                self.route(user+'/todolists/{folderid}', todo_lists)
                self.route(user+'/tasks/{itemid}', tasks)
                self.route(user+'/todolists/{folderid}/tasks/{itemid}', tasks)
                self.route(user+'/tasks/{itemid}/attachments/{attachmentid}', todo_attachment)
                self.route(user+'/todolists/{folderid}/tasks/{itemid}/attachments/{attachmentid}', todo_attachment)
