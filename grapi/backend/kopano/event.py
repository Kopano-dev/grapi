# SPDX-License-Identifier: AGPL-3.0-or-later
import binascii

import dateutil.parser
import falcon
import kopano

from kopano import Store
from .schema import event_schema
from .item import ItemResource, get_body, get_email, set_body
from .resource import _date, _start_end, _tzdate, set_date
from .schema import mr_schema
from .utils import (HTTPBadRequest, _server_store)

pattern_map = {
    'monthly': 'absoluteMonthly',
    'monthly_rel': 'relativeMonthly',
    'daily': 'daily',
    'weekly': 'weekly',
    'yearly': 'absoluteYearly',
    'yearly_rel': 'relativeYearly',
}
pattern_map_rev = dict((b, a) for (a, b) in pattern_map.items())

range_end_map = {
    'end_date': 'endDate',
    'forever': 'noEnd',
    'count': 'numbered',
}
range_end_map_rev = dict((b, a) for (a, b) in range_end_map.items())

show_as_map = {
    'free': 'free',
    'tentative': 'tentative',
    'busy': 'busy',
    'out_of_office': 'oof',
    'working_elsewhere': 'workingElsewhere',
    'unknown': 'unknown',
}


def recurrence_json(item):
    if isinstance(item, kopano.Item) and item.recurring:
        recurrence = item.recurrence
        # graph outputs some useless fields here, so we do too!
        j = {
            'pattern': {
                'type': pattern_map[recurrence.pattern],
                'interval': recurrence.interval,
                'month': recurrence.month or 0,
                'dayOfMonth': recurrence.monthday or 0,
                'index': recurrence.index or 'first',
                'firstDayOfWeek': recurrence.first_weekday,
            },
            'range': {
                'type': range_end_map[recurrence.range_type],
                'startDate': _date(recurrence.start, False, False),
                'endDate': _date(recurrence.end, False, False) if recurrence.range_type != 'no_end' else '0001-01-01',
                'numberOfOccurrences': recurrence.count if recurrence.range_type == 'occurrence_count' else 0,
                'recurrenceTimeZone': "",  # TODO: get recurrence timezone from recurrence blob (PidLidAppointmentTimeZoneDefinitionRecur)
            },
        }
        if recurrence.weekdays:
            j['pattern']['daysOfWeek'] = recurrence.weekdays
        return j


def recurrence_set(item, arg):
    # TODO order of setting recurrence attrs shouldn't matter

    if arg is None:
        item.recurring = False  # TODO pyko checks.. cleanup?
    else:
        item.recurring = True
        rec = item.recurrence

        if 'recurrenceTimezone' in arg['range']:
            item.timezone = arg['range']['recurrenceTimeZone']

        rec.pattern = pattern_map_rev[arg['pattern']['type']]
        rec.interval = arg['pattern']['interval']
        if 'daysOfWeek' in arg['pattern']:
            rec.weekdays = arg['pattern']['daysOfWeek']
        if 'dayOfMonth' in arg['pattern']:
            rec.monthday = arg['pattern']['dayOfMonth']
        if 'index' in arg['pattern']:
            rec.index = arg['pattern']['index']

        rec.range_type = range_end_map_rev[arg['range']['type']]
        if 'numberOfOccurrences' in arg['range']:
            rec.count = arg['range']['numberOfOccurrences']

        # TODO don't use hidden vars
        rec.start = dateutil.parser.parse(arg['range']['startDate'])
        if arg['range']['type'] == 'noEnd':
            rec.end = dateutil.parser.parse('31-12-4500')
        else:
            rec.end = dateutil.parser.parse(arg['range']['endDate'])

        rec._save()


def attendees_json(item):
    result = []
    for attendee in item.attendees():
        address = attendee.address
        data = {
            # TODO map response field names
            'status': {'response': attendee.response or 'None', 'time': _date(attendee.response_time)},
            'type': attendee.type_,
        }
        data.update(get_email(address))
        result.append(data)
    return result


def location_json(item):
    if not item.location or item.location.strip() == '':
        return None

    return {
        'displayName': item.location,
        'locationType': 'default',
    }


def location_set(item, arg):
    # TODO(longsleep): Support storing locationType.
    setattr(item, 'location', arg.get('displayName', ''))


def attendees_set(item, arg):
    for a in arg:
        email = a['emailAddress']
        addr = '%s <%s>' % (email.get('name', email['address']), email['address'])
        item.create_attendee(a['type'], addr)


def responsestatus_json(item):
    # 8.7.x does not have response_status attribute, so we must check.
    response_status = item.response_status if hasattr(item, 'response_status') else 'None'
    response_time = _date(item.replytime) if hasattr(item, 'replytime') else '0001-01-01T00:00:00Z'
    return {
        'response': response_status,
        'time': response_time,
    }


def event_type(item):
    if item.recurring:
        if isinstance(item, kopano.Occurrence):
            if item.exception:
                return 'exception'
            else:
                return 'occurrence'
        else:
            return 'seriesMaster'
    else:
        return 'singleInstance'


class EventResource(ItemResource):
    @classmethod
    def do_custom(cls, item, fields):
        if fields.get('attendees', None):
            # NOTE(longsleep): Sending can fail with NO_ACCCESS if no permission to outbox.
            item.send()

    @classmethod
    def do_custom_before_delete(cls, item):
        # If meeting is organised, sent cancellation
        if cls.fields['isOrganizer'](item):
            item.cancel()
            item.send()

    @classmethod
    def get_item_by_id(cls, folder, itemid):
        try:
            if isinstance(folder, Store):
                folder = cls.get_folder_by_id(folder, cls.default_folder_id)
            return folder.event(itemid)
        except binascii.Error:
            raise HTTPBadRequest('Event id is malformed')
        except kopano.errors.NotFoundError:
            raise falcon.HTTPNotFound(description='Item not found')

    default_folder_id = 'calendar'
    validation_schema = event_schema

    fields = ItemResource.fields.copy()
    fields.update({
        'id': lambda item: item.eventid,
        'subject': lambda item: item.subject,
        'recurrence': recurrence_json,
        'start': lambda req, item: _tzdate(item.start, item.tzinfo, req),
        'end': lambda req, item: _tzdate(item.end, item.tzinfo, req),
        'location': location_json,
        'importance': lambda item: item.urgency,
        'sensitivity': lambda item: item.sensitivity,
        'hasAttachments': lambda item: item.has_attachments,
        'body': lambda req, item: get_body(req, item),
        'isReminderOn': lambda item: item.reminder,
        'reminderMinutesBeforeStart': lambda item: item.reminder_minutes,
        'attendees': lambda item: attendees_json(item),
        'bodyPreview': lambda item: item.body_preview,
        'isAllDay': lambda item: item.all_day,
        'showAs': lambda item: show_as_map[item.show_as],
        'seriesMasterId': lambda item: item.item.eventid if item.recurring and isinstance(item, kopano.Occurrence) else None,
        'type': lambda item: event_type(item),
        'responseRequested': lambda item: item.response_requested,
        'iCalUId': lambda item: kopano.hex(kopano.bdec(item.icaluid)) if item.icaluid else None,  # graph uses hex!?
        'organizer': lambda item: get_email(item.from_),
        'isOrganizer': lambda item: item.from_.email == item.sender.email,
        'isCancelled': lambda item: item.canceled,
        'responseStatus': lambda item: responsestatus_json(item),
        # 8.7.x does not have onlinemeetingurl attribute, so we must check if its there for compatibility
        'onlineMeetingUrl': lambda item: item.onlinemeetingurl if hasattr(item, 'onlinemeetingurl') else ''
    })

    set_fields = {
        'subject': lambda item, arg: setattr(item, 'subject', arg),
        'location': lambda item, arg: location_set(item, arg),
        'body': set_body,
        'start': lambda item, arg: set_date(item, 'start', arg),
        'end': lambda item, arg: set_date(item, 'end', arg),
        'attendees': lambda item, arg: attendees_set(item, arg),
        'recurrence': recurrence_set,
        'isAllDay': lambda item, arg: setattr(item, 'all_day', arg),
        'isReminderOn': lambda item, arg: setattr(item, 'reminder', arg),
        'reminderMinutesBeforeStart': lambda item, arg: setattr(item, 'reminder_minutes', arg),
        # 8.7.x does not have onlinemeetingurl attribute, so we must check if its there for compatibility
        'onlineMeetingUrl': lambda item, arg: setattr(item, 'onlinemeetingurl', arg) if hasattr(item, 'onlinemeetingurl') else None,
    }
    message_class = 'IPM.Appointment'

    # TODO delta functionality seems to include expanding recurrences!? check with MSGE

    def handle_get_instances(self, req, resp, store, folderid, itemid):
        folder = self.get_folder_by_id(store, folderid)
        event = self.get_item_by_id(folder, itemid)
        start, end = _start_end(req)

        def yielder(**kwargs):
            for occ in event.occurrences(start, end, **kwargs):
                yield occ
        data = self.generator(req, yielder)
        self.respond(req, resp, data)

    def on_get(self, req, resp, userid=None, folderid=None, eventid=None, method=None):
        if method == 'attachments':
            handler = self.get_attachments

        elif method == 'instances':
            handler = self.handle_get_instances

        elif method:
            raise HTTPBadRequest("Unsupported event segment '%s'" % method)

        else:
            handler = self.get

        server, store, userid = _server_store(req, userid, self.options)
        handler(req, resp, store=store, folderid=folderid, itemid=eventid)

    def handle_post_accept(self, req, resp, store, folderid, itemid):
        folder = self.get_folder_by_id(store, folderid)
        item = self.get_item_by_id(folder, itemid)
        fields = self.load_json(req)
        _ = req.context.i18n.gettext
        self.validate_json(mr_schema, fields)
        item.accept(comment=fields.get('comment'), respond=(fields.get('sendResponse', True)), subject_prefix=_("Accepted"))
        resp.status = falcon.HTTP_202

    def handle_post_tentativelyAccept(self, req, resp, store, folderid, itemid):
        folder = self.get_folder_by_id(store, folderid)
        item = self.get_item_by_id(folder, itemid)
        fields = self.load_json(req)
        _ = req.context.i18n.gettext
        self.validate_json(mr_schema, fields)
        item.accept(comment=fields.get('comment'), tentative=True, respond=(fields.get('sendResponse', True)), subject_prefix=_("Tentatively accepted"))
        resp.status = falcon.HTTP_202

    def handle_post_decline(self, req, resp, store, folderid, itemid):
        folder = self.get_folder_by_id(store, folderid)
        item = self.get_item_by_id(folder, itemid)
        fields = self.load_json(req)
        _ = req.context.i18n.gettext
        self.validate_json(mr_schema, fields)
        item.decline(comment=fields.get('comment'), respond=(fields.get('sendResponse', True)), subject_prefix=_("Declined"))
        resp.status = falcon.HTTP_202

    def on_post(self, req, resp, userid=None, folderid=None, eventid=None, method=None):
        if method == 'accept':
            handler = self.handle_post_accept

        elif method == 'tentativelyAccept':
            handler = self.handle_post_tentativelyAccept

        elif method == 'decline':
            handler = self.handle_post_decline

        elif method == 'attachments':
            handler = self.add_attachments

        elif method:
            raise HTTPBadRequest("Unsupported event segment '%s'" % method)

        else:
            raise HTTPBadRequest("Unsupported in event")

        server, store, userid = _server_store(req, userid, self.options)
        handler(req, resp, store=store, folderid=folderid, itemid=eventid)

    def on_patch(self, req, resp, userid=None, folderid=None, eventid=None, method=None):
        server, store, userid = _server_store(req, userid, self.options)
        self.patch(req, resp, store=store, folderid=folderid, itemid=eventid)

    def on_delete(self, req, resp, userid=None, folderid=None, eventid=None):
        handler = self.delete

        server, store, userid = _server_store(req, userid, self.options)
        handler(req, resp, store=store, folderid=folderid, itemid=eventid)
