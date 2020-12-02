# SPDX-License-Identifier: AGPL-3.0-or-later
import codecs
import logging

import falcon
import kopano
from MAPI.Struct import MAPIErrorInvalidEntryid

from . import group  # import as module since this is a circular import
from .calendar import CalendarResource
from .contact import ContactResource
from .contactfolder import ContactFolderResource
from .event import EventResource
from .mailfolder import MailFolderResource
from .message import MessageResource
from .note import NoteResource
from .notebook import NotebookResource
from .profilephoto import ProfilePhotoResource
from .reminder import ReminderResource
from .resource import DEFAULT_TOP, Resource, _start_end
from .task import TaskResource
from .todolist import TodoListResource
from .utils import HTTPBadRequest, HTTPNotFound, _server_store, experimental


class UserImporter:
    def __init__(self):
        self.updates = []
        self.deletes = []

    def update(self, user):
        self.updates.append(user)

    def delete(self, user):
        self.deletes.append(user)


class DeletedUserResource(Resource):
    fields = {
        'id': lambda user: user.userid,
        #       '@odata.type': lambda item: '#microsoft.graph.message', # TODO
        '@removed': lambda item: {'reason': 'deleted'}  # TODO soft deletes
    }


class UserResource(Resource):
    fields = {
        'id': lambda user: user.userid,
        'displayName': lambda user: user.fullname,
        'jobTitle': lambda user: user.job_title,
        'givenName': lambda user: user.first_name,
        'mail': lambda user: user.email,
        'mobilePhone': lambda user: user.mobile_phone,
        'officeLocation': lambda user: user.office_location,
        'surname': lambda user: user.last_name,
        'userPrincipalName': lambda user: user.name,

        'companyName': lambda user: user.company,

        # 'accountEnabled': lambda user: user,
        # 'ageGroup': lambda user: user,
        # 'businessPhones': lambda user: user,
        # 'city': lambda user: user,
        # 'consentProvidedForMinor': lambda user: user,
        # 'country': lambda user: user,
        # 'creationType': lambda user: user,
        # 'createdDateTime': lambda user: user,
        # 'deletedDateTime': lambda user: user,
        # 'department': lambda user: user,
        # 'employeeId': lambda user: user,
        # 'externalUserState': lambda user: user,
        # 'externalUserStateChangeDateTime': lambda user: user,
        # 'faxNumber': lambda user: user,
        # 'imAddresses': lambda user: user,
        # 'isResourceAccount': lambda user: user,
        # 'lastPasswordChangeDateTime': lambda user: user,
        # 'legalAgeGroupClassification': lambda user: user,
        # 'mailNickname': lambda user: user,
        # 'onPremisesDistinguishedName': lambda user: user,
        # 'onPremisesDomainName': lambda user: user,
        # 'onPremisesImmutableId': lambda user: user,
        # 'onPremisesSamAccountName': lambda user: user,
        # 'onPremisesSecurityIdentifier': lambda user: user,
        # 'onPremisesSyncEnabled': lambda user: user,
        # 'onPremisesUserPrincipalName': lambda user: user,
        # 'otherMails': lambda user: user,
        # 'passwordPolicies': lambda user: user,
        # 'postalCode': lambda user: user,
        # 'preferredLanguage': lambda user: user,
        # 'proxyAddresses': lambda user: user,
        # 'showInAddressList': lambda user: user,
        # 'signInSessionsValidFromDateTime': lambda user: user,
        # 'state': lambda user: user,
        # 'streetAddress': lambda user: user,
        # 'usageLocation': lambda user: user,
        # 'userType': lambda user: user,
        # 'mailboxSettings': lambda user: user,
        # 'deviceEnrollmentLimit': lambda user: user,
        # 'aboutMe': lambda user: user,
        # 'birthday': lambda user: user,
        # 'hireDate': lambda user: user,
        # 'interests': lambda user: user,
        # 'mySite': lambda user: user,
        # 'pastProjects': lambda user: user,
        # 'preferredName': lambda user: user,
        # 'responsibilities': lambda user: user,
        # 'schools': lambda user: user,
        # 'skills': lambda user: user,
    }

    def delta(self, req, resp, server):
        args = self.parse_qs(req)
        token = args['$deltatoken'][0] if '$deltatoken' in args else None
        importer = UserImporter()
        newstate = server.sync_gab(importer, token)
        changes = [(o, UserResource) for o in importer.updates] + \
            [(o, DeletedUserResource) for o in importer.deletes]
        data = (changes, DEFAULT_TOP, 0, len(changes))
        deltalink = b"%s?$deltatoken=%s" % (req.path.encode('utf-8'), codecs.encode(newstate, 'ascii'))
        self.respond(req, resp, data, UserResource.fields, deltalink=deltalink)

    def handle_get(self, req, resp, store, server, userid):
        if userid:
            if userid == 'delta':
                self._handle_get_delta(req, resp, store=store, server=server)
            else:
                self._handle_get_with_userid(req, resp, store=store, server=server, userid=userid)
        else:
            self._handle_get_without_userid(req, resp, store=store, server=server)

    @experimental
    def _handle_get_delta(self, req, resp, store, server):
        req.context.deltaid = '{userid}'
        self.delta(req, resp, server=server)

    def _handle_get_with_userid(self, req, resp, store, server, userid):
        data = server.user(userid=userid)
        self.respond(req, resp, data)

    def _handle_get_without_userid(self, req, resp, store, server):
        args = self.parse_qs(req)
        userid = kopano.Store(server=server, mapiobj=server.mapistore).user.userid
        try:
            company = server.user(userid=userid).company
        except kopano.errors.NotFoundError:
            logging.warning('failed to get company for user %s', userid, exc_info=True)
            raise HTTPNotFound(description="The company wasn't found")
        query = None
        if '$search' in args:
            query = args['$search'][0]

        def yielder(**kwargs):
            yield from company.users(hidden=False, inactive=False, query=query, **kwargs)
        data = self.generator(req, yielder)
        self.respond(req, resp, data)

    @experimental
    def handle_get_reminderView(self, req, resp, store, server, userid):
        start, end = _start_end(req)

        def yielder(**kwargs):
            for occ in store.calendar.occurrences(start, end):
                if occ.reminder:
                    yield occ
        data = self.generator(req, yielder)
        self.respond(req, resp, data, ReminderResource.fields)

    @experimental
    def handle_get_memberOf(self, req, resp, store, server, userid):
        user = server.user(userid=userid)
        data = (user.groups(), DEFAULT_TOP, 0, 0)
        self.respond(req, resp, data, group.GroupResource.fields)

    @experimental
    def handle_get_photos(self, req, resp, store, server, userid):
        user = server.user(userid=userid)

        def yielder(**kwargs):
            photo = user.photo
            if photo:
                yield photo
        data = self.generator(req, yielder)
        self.respond(req, resp, data, ProfilePhotoResource.fields)

    # TODO redirect to other resources?
    def on_get(self, req, resp, userid=None, method=None):
        if not method:
            handler = self.handle_get

        elif method == 'mailFolders':
            handler = MailFolderResource.get_all

        elif method == 'notebooks':
            handler = NotebookResource.get_all

        elif method == 'todolists':
            handler = TodoListResource.get_all

        elif method == 'contactFolders':
            handler = ContactFolderResource.get_all

        elif method == 'calendars':
            handler = CalendarResource.get_all

        elif method == 'messages':  # TODO store-wide?
            handler = MessageResource.get_all

        elif method == 'notes':  # TODO store-wide?
            handler = NoteResource.get_all

        elif method == 'tasks':  # TODO store-wide?
            handler = TaskResource.get_all

        elif method == 'contacts':
            handler = ContactResource.get_all

        elif method == 'events':  # TODO multiple calendars?
            handler = EventResource.get_all

        elif method == 'calendarView':  # TODO multiple calendars?
            handler = CalendarResource.get_calendar_view

        elif method == 'reminderView':  # TODO multiple calendars?
            # TODO use restriction in pyko: calendar.reminders(start, end)?
            handler = self.handle_get_reminderView

        elif method == 'memberOf':
            handler = self.handle_get_memberOf

        elif method == 'photos':  # TODO multiple photos?
            handler = self.handle_get_photos

        elif method:
            raise HTTPBadRequest("Unsupported user segment '%s'" % method)

        else:
            raise HTTPBadRequest("Unsupported in user")

        try:
            server, store, userid = _server_store(req, userid, self.options)
        except MAPIErrorInvalidEntryid:
            raise HTTPBadRequest("Invalid entryid provided")
        if not userid and req.path.split('/')[-1] != 'users':
            userid = kopano.Store(server=server, mapiobj=server.mapistore).user.userid
        handler(req, resp, store=store, server=server, userid=userid)

    @experimental
    def handle_post_sendMail(self, req, resp, store):
        fields = self.load_json(req)
        message = self.create_item(store.outbox, fields['message'], MessageResource.set_fields)
        copy_to_sentmail = fields.get('SaveToSentItems', 'true') == 'true'
        message.send(copy_to_sentmail=copy_to_sentmail)
        resp.status = falcon.HTTP_202

    # TODO redirect to other resources?
    def on_post(self, req, resp, userid=None, method=None):
        if method == 'sendMail':
            handler = self.handle_post_sendMail

        elif method == 'contacts':
            handler = ContactResource.create

        elif method == 'messages':
            handler = MessageResource.create

        elif method == 'events':
            handler = EventResource.create

        elif method == 'notes':
            handler = NoteResource.create

        elif method == 'tasks':
            handler = TaskResource.create

        elif method == 'mailFolders':
            handler = MailFolderResource.create

        elif method == 'contactFolders':
            handler = ContactFolderResource.create

        elif method == 'calendars':
            handler = CalendarResource.create

        elif method == 'notebooks':
            handler = NotebookResource.create

        elif method == 'todolists':
            handler = TodoListResource.create

        elif method:
            raise HTTPBadRequest("Unsupported user segment '%s'" % method)

        else:
            raise HTTPBadRequest("Unsupported in user")

        server, store, userid = _server_store(req, userid, self.options)
        handler(req, resp, store=store)
