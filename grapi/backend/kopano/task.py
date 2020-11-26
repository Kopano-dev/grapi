# SPDX-License-Identifier: AGPL-3.0-or-later
import base64

import falcon
import logging

from MAPI.Tags import (
    PR_ATTACHMENT_CONTACTPHOTO, PR_GIVEN_NAME_W, PR_MIDDLE_NAME_W,
    PR_SURNAME_W, PR_NICKNAME_W, PR_TITLE_W, PR_GENERATION_W, PR_BODY_W,
    PR_COMPANY_NAME_W, PR_MOBILE_TELEPHONE_NUMBER_W, PR_CHILDRENS_NAMES_W,
    PR_BIRTHDAY, PR_SPOUSE_NAME_W, PR_INITIALS_W, PR_DISPLAY_NAME_PREFIX_W,
    PR_DEPARTMENT_NAME_W, PR_OFFICE_LOCATION_W, PR_PROFESSION_W,
    PR_MANAGER_NAME_W, PR_ASSISTANT_W, PR_BUSINESS_HOME_PAGE_W,
    PR_HOME_TELEPHONE_NUMBER_W, PR_HOME2_TELEPHONE_NUMBER_W,
    PR_BUSINESS_TELEPHONE_NUMBER_W, PR_BUSINESS2_TELEPHONE_NUMBER_W,
    PR_HOME_ADDRESS_STREET_W, PR_HOME_ADDRESS_CITY_W,
    PR_HOME_ADDRESS_POSTAL_CODE_W, PR_HOME_ADDRESS_STATE_OR_PROVINCE_W,
    PR_HOME_ADDRESS_COUNTRY_W, PR_OTHER_ADDRESS_STREET_W,
    PR_OTHER_ADDRESS_CITY_W, PR_OTHER_ADDRESS_POSTAL_CODE_W,
    PR_OTHER_ADDRESS_STATE_OR_PROVINCE_W, PR_OTHER_ADDRESS_COUNTRY_W,
    PR_READ_RECEIPT_REQUESTED, PR_FLAG_STATUS, PR_FLAG_COMPLETE_TIME
)

from . import attachment  # import as module since this is a circular import
from .item import ItemResource, get_body, get_email, set_body
from .resource import DEFAULT_TOP, _date, parse_datetime_timezone, _tzdate
from .utils import HTTPBadRequest, _folder, _item, _server_store, _set_value_by_tag, experimental


PR_MESSAGE_DUE_DATE = "PT_SYSTIME:PSETID_Task:0x8105"
PR_MESSAGE_START_DATE = "PT_SYSTIME:PSETID_Task:0x8104"

MESSAGE_FLAG_STATUS_KEY = 'flagStatus'
MESSAGE_FLAG_STATUS_NOT_FLAGGED = 'notFlagged'
MESSAGE_FLAG_STATUS_KEY_COMPLETE = 'complete'
MESSAGE_FLAG_STATUS_KEY_FLAGGED = 'flagged'
MESSAGE_FLAG_COMPLETE_TIME_KEY = 'completedDateTime'
MESSAGE_FLAG_DUE_DATE_KEY = "dueDateTime"
MESSAGE_FLAG_START_DATE_KEY = "startDateTime"


def _get_flag(req, item) -> dict:
    flag = {}
    # Get flag status
    try:
        status = item.get(PR_FLAG_STATUS)
        if isinstance(status, int):
            if status == 0:
                flag[MESSAGE_FLAG_STATUS_KEY] = MESSAGE_FLAG_STATUS_NOT_FLAGGED
            if status == 1:
                flag[MESSAGE_FLAG_STATUS_KEY] = MESSAGE_FLAG_STATUS_KEY_COMPLETE
            if status == 2:
                flag[MESSAGE_FLAG_STATUS_KEY] = MESSAGE_FLAG_STATUS_KEY_FLAGGED
    except NameError:
        logging.info("Item flag status not set")
    # Get complete time
    try:
        complete = item.get(PR_FLAG_COMPLETE_TIME)
        flag[MESSAGE_FLAG_COMPLETE_TIME_KEY] = _tzdate(complete, item.tzinfo, req)
    except NameError:
        logging.info("Item flag complete time not set")
    # Get start date
    try:
        start = item.get(PR_MESSAGE_START_DATE)
        flag[MESSAGE_FLAG_START_DATE_KEY] = _tzdate(start, item.tzinfo, req)
    except NameError:
        logging.info("Item flag complete time not set")
    # Get due date
    try:
        due = item.get(PR_MESSAGE_DUE_DATE)
        flag[MESSAGE_FLAG_DUE_DATE_KEY] = _tzdate(due, item.tzinfo, req)
    except NameError:
        logging.info("Item flag complete time not set")
    return flag


def _set_flag(item, arg: dict) -> None:
    # Set flag status
    if MESSAGE_FLAG_STATUS_KEY in arg:
        if arg[MESSAGE_FLAG_STATUS_KEY] == MESSAGE_FLAG_STATUS_NOT_FLAGGED:
            _set_value_by_tag(item, 0, PR_FLAG_STATUS)
        if arg[MESSAGE_FLAG_STATUS_KEY] == MESSAGE_FLAG_STATUS_KEY_COMPLETE:
            _set_value_by_tag(item, 1, PR_FLAG_STATUS)
        if arg[MESSAGE_FLAG_STATUS_KEY] == MESSAGE_FLAG_STATUS_KEY_FLAGGED:
            _set_value_by_tag(item, 2, PR_FLAG_STATUS)

    # Set complete time
    if MESSAGE_FLAG_COMPLETE_TIME_KEY in arg:
        _set_value_by_tag(
            item,
            parse_datetime_timezone(
                arg[MESSAGE_FLAG_COMPLETE_TIME_KEY],
                MESSAGE_FLAG_COMPLETE_TIME_KEY
            ),
            PR_FLAG_COMPLETE_TIME
        )

    # Set due date
    if MESSAGE_FLAG_DUE_DATE_KEY in arg:
        _set_value_by_tag(
            item,
            parse_datetime_timezone(
                arg[MESSAGE_FLAG_DUE_DATE_KEY],
                MESSAGE_FLAG_COMPLETE_TIME_KEY
            ),
            PR_MESSAGE_DUE_DATE
        )

    # Set start date
    if MESSAGE_FLAG_START_DATE_KEY in arg:
        _set_value_by_tag(
            item,
            parse_datetime_timezone(
                arg[MESSAGE_FLAG_START_DATE_KEY],
                MESSAGE_FLAG_COMPLETE_TIME_KEY
            ),
            PR_MESSAGE_START_DATE
        )


class DeletedTodoResource(ItemResource):
    fields = {
        '@odata.type': lambda item: '#microsoft.graph.todo',  # TODO
        'id': lambda item: item.entryid,
        '@removed': lambda item: {'reason': 'deleted'}  # TODO soft deletes
    }


@experimental
class TaskResource(ItemResource):
    fields = ItemResource.fields.copy()
    fields.update({
        # TODO pyko shortcut for event messages
        # TODO eventMessage resource?
        '@odata.type': lambda item: '#microsoft.graph.note' if item.message_class.startswith('IPM.Schedule.Meeting.') else None,
        'subject': lambda item: item.subject,
        'body': lambda req, item: get_body(req, item),
        'flag': lambda req, item: _get_flag(req, item),
        'from': lambda item: get_email(item.from_),
        'sender': lambda item: get_email(item.sender),
        'toRecipients': lambda item: [get_email(to) for to in item.to],
        'ccRecipients': lambda item: [get_email(cc) for cc in item.cc],
        'bccRecipients': lambda item: [get_email(bcc) for bcc in item.bcc],
        'sentDateTime': lambda item: _date(item.sent) if item.sent else None,
        'receivedDateTime': lambda item: _date(item.received) if item.received else None,
        'hasAttachments': lambda item: item.has_attachments,
        'internetMessageId': lambda item: item.messageid,
        'importance': lambda item: item.urgency,
        'parentFolderId': lambda item: item.folder.entryid,
        'conversationId': lambda item: item.conversationid,
        'isRead': lambda item: item.read,
        'isReadReceiptRequested': lambda item: item.read_receipt,
        'isDeliveryReceiptRequested': lambda item: item.read_receipt,
        'replyTo': lambda item: [get_email(to) for to in item.replyto],
        'bodyPreview': lambda item: item.body_preview,
    })

    set_fields = {
        'subject': lambda item, arg: setattr(item, 'subject', arg),
        'body': set_body,
        'importance': lambda item, arg: setattr(item, 'urgency', arg),
        'flag': lambda item, arg: _set_flag(item, arg),

    }
    message_class = 'IPM.Task'

    deleted_resource = DeletedTodoResource

    relations = {
        'attachments': lambda note: (note.attachments, attachment.FileAttachmentResource),  # TODO embedded
    }

    def handle_get(self, req, resp, store, folder, itemid):
        if itemid == 'delta':  # TODO move to MailFolder resource somehow?
            self._handle_get_delta(req, resp, store=store, folder=folder)
        else:
            self._handle_get_with_itemid(req, resp, store=store, folder=folder, itemid=itemid)

    def _handle_get_delta(self, req, resp, store, folder):
        req.context.deltaid = '{itemid}'
        self.delta(req, resp, folder=folder)

    def _handle_get_with_itemid(self, req, resp, store, folder, itemid):
        item = _item(folder, itemid)
        self.respond(req, resp, item)

    def handle_get_attachments(self, req, resp, store, folder, itemid):
        item = _item(folder, itemid)
        attachments = list(attachment.get_attachments(item))
        data = (attachments, DEFAULT_TOP, 0, len(attachments))
        self.respond(req, resp, data)

    def on_get(self, req, resp, userid=None, folderid=None, itemid=None, method=None):
        handler = None

        if not method:
            handler = self.handle_get

        elif method == 'attachments':
            handler = self.handle_get_attachments

        elif method:
            raise HTTPBadRequest("Unsupported note segment '%s'" % method)

        else:
            raise HTTPBadRequest("Unsupported in note")

        server, store, userid = _server_store(req, userid, self.options)
        folder = _folder(store, folderid or 'tasks')  # TODO all folders?
        handler(req, resp, store=store, folder=folder, itemid=itemid)

    def handle_post_attachments(self, req, resp, store, folder, item):
        fields = self.load_json(req)
        odataType = fields.get('@odata.type', None)
        if odataType == '#microsoft.graph.fileAttachment':  # TODO other types
            att = item.create_attachment(fields['name'], base64.urlsafe_b64decode(fields['contentBytes']))
            self.respond(req, resp, att, attachment.AttachmentResource.fields)
            resp.status = falcon.HTTP_201
        else:
            raise HTTPBadRequest("Unsupported attachment @odata.type: '%s'" % odataType)

    def handle_post_copy(self, req, resp, store, folder, item):
        self._handle_post_copyOrMove(req, resp, store=store, item=item)

    def handle_post_move(self, req, resp, store, folder, item):
        self._handle_post_copyOrMove(req, resp, store=store, item=item, move=True)

    def _handle_post_copyOrMove(self, req, resp, store, item, move=False):
        fields = self.load_json(req)
        to_folder = store.folder(entryid=fields['destinationId'].encode('ascii'))  # TODO ascii?
        if not move:
            item = item.copy(to_folder)
        else:
            item = item.move(to_folder)

    def on_post(self, req, resp, userid=None, folderid=None, itemid=None, method=None):
        handler = None

        if method == 'attachments':
            handler = self.handle_post_attachments

        elif method == 'copy' or method == 'microsoft.graph.copy':
            handler = self.handle_post_copy

        elif method == 'move' or method == 'microsoft.graph.move':
            handler = self.handle_post_move

        elif method:
            raise HTTPBadRequest("Unsupported message segment '%s'" % method)

        else:
            raise HTTPBadRequest("Unsupported in message")

        server, store, userid = _server_store(req, userid, self.options)
        folder = _folder(store, folderid or 'tasks')  # TODO all folders?
        item = _item(folder, itemid)
        handler(req, resp, store=store, folder=folder, item=item)

    def handle_patch(self, req, resp, store, folder, itemid):
        item = _item(folder, itemid)
        fields = self.load_json(req)

        for field, value in fields.items():
            if field in self.set_fields:
                self.set_fields[field](item, value)

        self.respond(req, resp, item, TaskResource.fields)

    def on_patch(self, req, resp, userid=None, folderid=None, itemid=None, method=None):
        handler = None

        if not method:
            handler = self.handle_patch

        else:
            raise HTTPBadRequest("Unsupported note segment '%s'" % method)

        server, store, userid = _server_store(req, userid, self.options)
        folder = _folder(store, folderid or 'tasks')  # TODO all folders?
        handler(req, resp, store=store, folder=folder, itemid=itemid)

    def handle_delete(self, req, resp, store, itemid):
        item = _item(store, itemid)

        store.delete(item)

        self.respond_204(resp)

    def on_delete(self, req, resp, userid=None, folderid=None, itemid=None, method=None):
        handler = None

        if not method:
            handler = self.handle_delete

        else:
            raise HTTPBadRequest("Unsupported note segment '%s'" % method)

        server, store, userid = _server_store(req, userid, self.options)
        handler(req, resp, store=store, itemid=itemid)


class EmbeddedTaskResource(TaskResource):
    fields = TaskResource.fields.copy()
    fields.update({
        'id': lambda item: '',
    })
    del fields['@odata.etag']  # TODO check MSG
    del fields['parentFolderId']
    del fields['changeKey']
