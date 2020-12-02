# SPDX-License-Identifier: AGPL-3.0-or-later

import logging

from kopano.errors import NotFoundError

from .event import EventResource
from .folder import FolderResource
from .resource import _dumpb_json, _start_end, _tzdate, parse_datetime_timezone
from .schema import event_schema, get_schedule_schema
from .utils import HTTPBadRequest, _folder, _server_store, experimental


def get_fbinfo(req, block):
    return {
        'status': block.status,
        'start': _tzdate(block.start, None, req),
        'end': _tzdate(block.end, None, req)
    }


class CalendarResource(FolderResource):
    @classmethod
    def default_folders_list(cls, store):
        return store.calendars

    @classmethod
    def name_field(cls, fields: dict):
        return fields['name']

    default_folder_id = 'calendar'

    validation_schema = calendar_schema

    fields = FolderResource.fields.copy()
    fields.update({
        'name': lambda folder: folder.name,
    })

    container_classes = ('IPF.Appointment',)
    container_class = 'IPF.Appointment'

    @classmethod
    def get_calendar_view(cls, req, resp, store, server, userid):
        cls.get_calendar_view_in_folder(req, resp, store=store)

    @classmethod
    def get_calendar_view_in_folder(cls, req, resp, folderid=None, store=None):
        if folderid:
            folder = cls.get_folder_by_id(store, folderid)
        else:
            folder = store
        start, end = _start_end(req)

        def yielder(**kwargs):
            for occ in folder.occurrences(start, end, **kwargs):
                yield occ
        data = cls.generator(req, yielder)
        cls.respond(req, resp, data, EventResource.fields)

    def on_get(self, req, resp, userid=None, folderid=None, method=None):
        if method == 'calendarView':
            handler = self.get_calendar_view_in_folder

        elif method == 'events':
            handler = EventResource.get_all_from_folder

        elif method:
            raise HTTPBadRequest("Unsupported calendar segment '%s'" % method)

        else:
            handler = self.get

        server, store, userid = _server_store(req, userid, self.options)
        handler(req, resp, store=store, folderid=folderid)

    @experimental
    def handle_post_schedule(self, req, resp, store, folderid):
        fields = self.load_json(req)
        self.validate_json(get_schedule_schema, fields)

        freebusytimes = []

        server, store, userid = _server_store(req, None, self.options)

        email_addresses = fields['schedules']
        start = parse_datetime_timezone(fields['startTime'], 'startTime')
        end = parse_datetime_timezone(fields['endTime'], 'endTime')
        # TODO: implement availabilityView https://docs.microsoft.com/en-us/graph/outlook-get-free-busy-schedule
        availability_view_interval = fields.get('availabilityViewInterval', 60)

        for address in email_addresses:
            try:
                user = server.user(email=address)
            except NotFoundError:
                continue  # TODO: silent ignore or raise exception?

            fbdata = {
                'scheduleId': address,
                'availabilityView': '',
                'scheduleItems': [],
                'workingHours': {},
            }

            try:
                blocks = user.freebusy.blocks(start=start, end=end)
            except NotFoundError:
                logging.warning('no public store available, unable to retrieve freebusy data')
                continue

            if not blocks:
                continue

            fbdata['scheduleItems'] = [get_fbinfo(req, block) for block in blocks]
            freebusytimes.append(fbdata)

        data = {
            "@odata.context": "https://graph.microsoft.com/v1.0/$metadata#Collection(microsoft.graph.scheduleInformation)",
            "value": freebusytimes,
        }
        resp.content_type = 'application/json'
        resp.body = _dumpb_json(data)

    def on_post(self, req, resp, userid=None, folderid=None, method=None):
        if method == 'events':
            handler = EventResource.create_in_folder

        elif method == 'getSchedule':
            handler = self.handle_post_schedule

        elif method:
            raise HTTPBadRequest("Unsupported calendar segment '%s'" % method)

        else:
            raise HTTPBadRequest("Unsupported in calendar")

        server, store, userid = _server_store(req, userid, self.options)
        handler(req, resp, store=store, folderid=folderid)
