# SPDX-License-Identifier: AGPL-3.0-or-later

from urllib.parse import parse_qs
import html

import falcon


def _parse_qs(req):
    args = parse_qs(req.query_string)
    for arg, values in args.items():
        if len(values) > 1:
            raise HTTPBadRequest("Query option '%s' was specified more than once, but it must be specified at most once." % arg)

    for key in ('$top', '$skip'):
        if key in args:
            value = args[key][0]
            if not value.isdigit():
                raise HTTPBadRequest("Invalid value '%s' for %s query option found. The %s query option requires a non-negative integer value." % (value, key, key))

    return args


class HTTPBadRequest(falcon.HTTPBadRequest):
    def __init__(self, msg):
        msg = html.escape(msg)
        super().__init__(None, msg)


class Resource:
    def __init__(self, options):
        self.options = options

    def parse_qs(self, req):
        return _parse_qs(req)
