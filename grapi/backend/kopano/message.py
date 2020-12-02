# SPDX-License-Identifier: AGPL-3.0-or-later
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
from .schema import message_schema
from .item import ItemResource, get_body, get_email, set_body
from .resource import _date, parse_datetime_timezone, _tzdate
from .utils import HTTPBadRequest, _server_store, _set_value_by_tag, experimental


def set_torecipients(item, arg: dict) -> None:
    addrs = []
    for a in arg:
        a = a['emailAddress']
        addrs.append('%s <%s>' % (a.get('name', a['address']), a['address']))
    item.to = ';'.join(addrs)


def set_ccrecipients(item, arg: dict) -> None:
    addrs = []
    for a in arg:
        a = a['emailAddress']
        addrs.append('%s <%s>' % (a.get('name', a['address']), a['address']))
    item.cc = ';'.join(addrs)


def set_bccrecipients(item, arg: dict) -> None:
    addrs = []
    for a in arg:
        a = a['emailAddress']
        addrs.append('%s <%s>' % (a.get('name', a['address']), a['address']))
    item.bcc = ';'.join(addrs)


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


class DeletedMessageResource(ItemResource):
    fields = {
        '@odata.type': lambda item: '#microsoft.graph.message',  # TODO
        'id': lambda item: item.entryid,
        '@removed': lambda item: {'reason': 'deleted'}  # TODO soft deletes
    }


@experimental
class MessageResource(ItemResource):
    @classmethod
    def default_folder_create(cls, store):
        return store.drafts

    default_folder_id = 'inbox'
    alt_folder_id = 'drafts'
    validation_schema = message_schema

    fields = ItemResource.fields.copy()
    fields.update({
        # TODO pyko shortcut for event messages
        # TODO eventMessage resource?
        '@odata.type': lambda item: '#microsoft.graph.eventMessage' if item.message_class.startswith('IPM.Schedule.Meeting.') else None,
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
        'toRecipients': set_torecipients,
        'isRead': lambda item, arg: setattr(item, 'read', arg),
        'ccRecipients': set_ccrecipients,
        'bccRecipients': set_bccrecipients,
        'importance': lambda item, arg: setattr(item, 'urgency', arg),
        # 'isDeliveryReceiptRequested': lambda item, arg: setattr(item, 'read_receipt', arg),
        'isDeliveryReceiptRequested': lambda item, arg: _set_value_by_tag(item, arg, PR_READ_RECEIPT_REQUESTED),
        # 'bodyPreview': lambda item, arg: _set_value_by_tag(item, arg, PR_BODY_W),
        'flag': lambda item, arg: _set_flag(item, arg),

    }
    message_class = 'IPM.Note'

    deleted_resource = DeletedMessageResource

    relations = {
        'attachments': lambda message: (message.attachments, attachment.FileAttachmentResource),  # TODO embedded
    }

    def on_get(self, req, resp, userid=None, folderid=None, itemid=None, method=None):
        if not method:
            handler = self.get

        elif method == 'attachments':
            handler = self.get_attachments

        elif method:
            raise HTTPBadRequest("Unsupported message segment '%s'" % method)

        else:
            raise HTTPBadRequest("Unsupported in message")

        server, store, userid = _server_store(req, userid, self.options)
        handler(req, resp, store=store, folderid=folderid, itemid=itemid)

    def handle_post_createReply(self, req, resp, store, folderid, itemid):
        self._handle_post_createRaplyOrCreateReplyAll(req, resp, store, folderid, itemid, False)

    def handle_post_createReplyAll(self, req, resp, store, folderid, itemid):
        self._handle_post_createRaplyOrCreateReplyAll(req, resp, store, folderid, itemid, True)

    def _handle_post_createRaplyOrCreateReplyAll(self, req, resp, store, folderid, itemid, replyAll: bool):
        folder = self.get_folder_by_id(store, folderid)
        item = self.get_item_by_id(folder, itemid)
        fields = self.load_json(req)
        if 'message' in fields:
            fields = fields['message']
        else:
            fields = {}

        new_item = item.reply(all=replyAll)
        for field in self.set_fields:
            if field in fields:
                self.set_fields[field](new_item, fields[field])

        self.respond(req, resp, new_item, MessageResource.fields)
        resp.status = falcon.HTTP_201

    def handle_post_send(self, req, resp, store, folderid, itemid):
        folder = self.get_folder_by_id(store, folderid)
        item = self.get_item_by_id(folder, itemid)
        item.send()
        resp.status = falcon.HTTP_202

    def on_post(self, req, resp, userid=None, folderid=None, itemid=None, method=None):
        if method == 'createReply' or method == 'microsoft.graph.createReply':
            handler = self.handle_post_createReply

        elif method == 'createReplyAll' or method == 'microsoft.graph.createReplyAll':
            handler = self.handle_post_createReplyAll

        elif method == 'attachments':
            handler = self.add_attachments

        elif method == 'copy' or method == 'microsoft.graph.copy':
            handler = self.copy

        elif method == 'move' or method == 'microsoft.graph.move':
            handler = self.move

        elif method == 'send' or method == 'microsoft.graph.send':
            handler = self.handle_post_send

        # TODO add forward message
        # elif method == 'send' or method == 'microsoft.graph.forward':
        #     handler = self.handle_post_forward

        elif method:
            raise HTTPBadRequest("Unsupported message segment '%s'" % method)

        else:
            raise HTTPBadRequest("Unsupported in message")

        server, store, userid = _server_store(req, userid, self.options)
        handler(req, resp, store=store, folderid=folderid, itemid=itemid)

    def on_patch(self, req, resp, userid=None, folderid=None, itemid=None, method=None):
        if not method:
            handler = self.patch
        else:
            raise HTTPBadRequest("Unsupported message segment '%s'" % method)

        server, store, userid = _server_store(req, userid, self.options)
        handler(req, resp, store=store, folderid=folderid, itemid=itemid)

    def on_delete(self, req, resp, userid=None, folderid=None, itemid=None, method=None):
        if not method:
            handler = self.delete
        else:
            raise HTTPBadRequest("Unsupported message segment '%s'" % method)

        server, store, userid = _server_store(req, userid, self.options)
        handler(req, resp, store=store, folderid=folderid, itemid=itemid)


class EmbeddedMessageResource(MessageResource):
    fields = MessageResource.fields.copy()
    fields.update({
        'id': lambda item: '',
    })
    del fields['@odata.etag']  # TODO check MSG
    del fields['parentFolderId']
    del fields['changeKey']
