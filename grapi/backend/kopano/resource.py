# SPDX-License-Identifier: AGPL-3.0-or-later
import datetime
import logging
import time

import dateutil.parser
import pytz
import tzlocal

import falcon

from grapi.api.v1.resource import HTTPBadRequest
from grapi.api.v1.resource import Resource as BaseResource
from grapi.api.v1.resource import _dumpb_json, _encode_qs, _parse_qs
from grapi.api.v1.timezone import to_timezone

from .utils import _handle_exception, _folder

UTC = pytz.utc
LOCAL = tzlocal.get_localzone()

DEFAULT_TOP = 10


def _date(d, local=False, show_time=True):
    if d is None:
        return '0001-01-01T00:00:00.000000Z'
    fmt = '%Y-%m-%d'
    if show_time:
        fmt += 'T%H:%M:%S'
    # Microseconds need to be set
    # if d.microsecond:
    fmt += '.%f'
    if not local:
        fmt += 'Z'
    # TODO make pyko not assume naive localtime..
    seconds = time.mktime(d.timetuple())
    d = datetime.datetime.utcfromtimestamp(seconds)
    return d.strftime(fmt)


# TODO: re-order args? req, d, tzinfo=None?
def _tzdate(d, tzinfo, req):
    if d is None:
        return None

    fmt = '%Y-%m-%dT%H:%M:%S'

    if d.tzinfo is None:
        # NOTE(longsleep): pyko uses naive localtime..
        d = LOCAL.localize(d)

    # Apply timezone preference when set in request context.
    prefer_tz = req.context.prefer.get('outlook.timezone')
    if prefer_tz and prefer_tz[0]:
        d = d.astimezone(prefer_tz[0]).replace(tzinfo=None)
        prefer_timeZone = prefer_tz[1]
    else:
        prefer_timeZone = 'UTC'
        d = d.astimezone(UTC).replace(tzinfo=None)

    return {
        'dateTime': d.strftime(fmt),
        'timeZone': prefer_timeZone,  # TODO error
    }


def _naive_local(d):  # TODO make pyko not assume naive localtime..
    if d.tzinfo is not None:
        return d.astimezone(LOCAL).replace(tzinfo=None)
    else:
        return d


def parse_datetime_timezone(datetime_timezone, field):
    try:
        tz = to_timezone(datetime_timezone.get('timeZone', 'UTC'))
    except Exception:
        logging.debug('failed to parse timezone value when setting date to \'%s\'', field)
        raise HTTPBadRequest('The timeZone value of field \'%s\' is not supported.' % field)
    try:
        d = dateutil.parser.parse(datetime_timezone['dateTime'], ignoretz=True)
    except ValueError:
        logging.debug('failed to parse date when setting to \'%s\'', exc_info=True)
        raise HTTPBadRequest('The date value of field \'%s\' is invalid.' % field)

    return tz.localize(d).astimezone(LOCAL).replace(tzinfo=None)


def set_date(item, field, arg):
    d = parse_datetime_timezone(arg, field)
    setattr(item, field, d)


def _parse_date(args, key):
    try:
        value = args[key][0]
    except KeyError:
        raise HTTPBadRequest(
            'This request requires a time window specified by the query string parameters StartDateTime and EndDateTime.')
    try:
        return _naive_local(dateutil.parser.parse(value))
    except ValueError:
        logging.debug('failed to parse date in parameter \'%s\', key', exc_info=True)
        raise HTTPBadRequest('The date value of parameter \'%s\' is invalid.' % key)


def _start_end(req):
    args = _parse_qs(req)
    return _parse_date(args, 'startDateTime'), _parse_date(args, 'endDateTime')


class Resource(BaseResource):
    fields = None
    set_fields = None
    default_folder_id = None
    alt_folder_id = None

    def __init__(self, options):
        super().__init__(options)

    def exceptionHandler(self, ex, req, resp, **params):
        _handle_exception(ex, req)

    @classmethod
    def get_folder_by_id(cls, store, folderid):
        folder = _folder(store, folderid or cls.default_folder_id)
        if not folder:
            raise falcon.HTTPNotFound(description="Folder not found")
        return folder

    @classmethod
    def get_fields(cls, req, obj, fields, all_fields):
        fields = fields or all_fields or cls.fields
        result = {}
        for f in fields:
            accessor = all_fields.get(f, None)
            if accessor is not None:
                if accessor.__code__.co_argcount == 1:
                    # TODO(longsleep): Remove this mode of operation.
                    result[f] = accessor(obj)
                else:
                    result[f] = accessor(req, obj)

        # TODO do not handle here
        if '@odata.type' in result and not result['@odata.type']:
            del result['@odata.type']
        return result

    @classmethod
    def json(cls, req, obj, fields, all_fields, multi=False, expand=None):
        data = cls.get_fields(req, obj, fields, all_fields)
        if not multi:
            data['@odata.context'] = req.path
        if expand:
            data.update(expand)
        return _dumpb_json(data)

    @classmethod
    def json_multi(cls, req, obj, fields, all_fields, top, skip, count, deltalink, add_count=False):
        header = b'{\n'
        header += b'  "@odata.context": "%s",\n' % req.path.encode('utf-8')
        if add_count:
            header += b'  "@odata.count": "%d",\n' % count
        if deltalink:
            header += b'  "@odata.deltaLink": "%s",\n' % deltalink
        else:
            path = req.path
            if req.query_string:
                args = cls.parse_qs(req)
                if '$skip' in args:
                    del args['$skip']
            else:
                args = {}
            args['$skip'] = skip + top
            nextLink = path + '?' + _encode_qs(list(args.items()))
            header += b'  "@odata.nextLink": "%s",\n' % (_dumpb_json(nextLink)[1:-1])
        header += b'  "value": [\n'
        yield header
        first = True
        try:
            for o in obj:
                if isinstance(o, tuple):
                    o, resource = o
                    all_fields = resource.fields
                if not first:
                    yield b',\n'
                first = False
                wa = cls.json(req, o, fields, all_fields, multi=True)
                yield b'\n'.join([b'    ' + line for line in wa.splitlines()])
        except Exception:
            logging.exception("failed to marshal %s JSON response", req.path)
        yield b'\n  ]\n}'

    @classmethod
    def respond(cls, req, resp, obj, all_fields=None, deltalink=None):
        # determine fields
        args = cls.parse_qs(req)
        if '$select' in args:
            fields = set(args['$select'][0].split(',') + ['@odata.type', '@odata.etag', 'id'])
        else:
            fields = None

        resp.content_type = "application/json"
        prefer_body_content_type = req.context.prefer.get('outlook.body-content-type', raw=True)
        if prefer_body_content_type in ('text', 'html'):
            req.context.prefer.update('outlook.body-content-type', prefer_body_content_type)

        # multiple objects: stream
        if isinstance(obj, tuple):
            obj, top, skip, count = obj
            add_count = '$count' in args and args['$count'][0] == 'true'

            resp.stream = cls.json_multi(req, obj, fields, all_fields or cls.fields, top, skip, count, deltalink,
                                         add_count)

        # single object
        else:
            # expand sub-objects # TODO stream?
            expand = None
            if '$expand' in args:
                expand = {}
                for field in args['$expand'][0].split(','):
                    if hasattr(cls, 'relations') and field in cls.relations:
                        objs, resource = cls.relations[field](obj)
                        expand[field] = [cls.get_fields(req, obj2, resource.fields, resource.fields) for obj2 in objs()]

                    elif hasattr(cls, 'expansions') and field in cls.expansions:
                        obj2, resource = cls.expansions[field](obj)
                        # TODO item@odata.context, @odata.type..
                        expand[field.split('/')[1]] = cls.get_fields(req, obj2, resource.fields, resource.fields)
            resp.body = cls.json(req, obj, fields, all_fields or cls.fields, expand=expand)

    @staticmethod
    def generator(req, generator, count=0, restriction=None):
        # determine pagination and ordering
        args = _parse_qs(req)
        top = int(args['$top'][0]) if '$top' in args else DEFAULT_TOP
        skip = int(args['$skip'][0]) if '$skip' in args else 0
        order = args['$orderby'][0].split(',') if '$orderby' in args else None
        if order:
            order = tuple(('-' if len(o.split()) > 1 and o.split()[1] == 'desc' else '') + o.split()[0] for o in order)

        if restriction is not None:
            return (generator(restriction=restriction, page_start=skip, page_limit=top, order=order), top, skip, count)
        else:
            return (generator(page_start=skip, page_limit=top, order=order), top, skip, count)

    @classmethod
    def create_item(cls, folder, fields, all_fields=None):
        # TODO item.update and/or only save in the end
        item = folder.create_item()

        for field in (all_fields or cls.set_fields):
            if field in fields:
                (all_fields or cls.set_fields)[field](item, fields[field])

        return item

    @classmethod
    def folder_gen(cls, req, folder):
        args = cls.parse_qs(req)  # TODO generalize
        # TODO implement odata
        # TODO For now we will at least provide a way to filter by 'isRead eq false' to get unread mails
        # TODO filter will for now override search
        if '$filter' in args:
            if "isRead eq false" in args['$filter']:
                query = "read:false"

                def yielder(**kwargs):
                    for item in folder.items(query=query):
                        yield item

                return cls.generator(req, yielder, 0)

        if '$search' in args:
            query = args['$search'][0]

            def yielder(**kwargs):
                for item in folder.items(query=query):
                    yield item

            return cls.generator(req, yielder, 0)
        else:
            return cls.generator(req, folder.items, folder.count)
