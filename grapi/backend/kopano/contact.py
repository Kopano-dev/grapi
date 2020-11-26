# SPDX-License-Identifier: AGPL-3.0-or-later

from .item import ItemResource
import logging
from datetime import datetime
from .item import ItemResource
from .resource import _date
from .utils import HTTPBadRequest, _folder, _item, _server_store, _set_value_by_tag, _set_value_per_tag, experimental

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
)

# TODO import constants
PidLidYomiFirstName = 'PT_UNICODE:PSETID_Address:0x802C'
PidLidYomiLastName = 'PT_UNICODE:PSETID_Address:0x802D'
PidLidYomiCompanyName = 'PT_UNICODE:PSETID_Address:0x802E'
PidLidFileUnder = 'PT_UNICODE:PSETID_Address:0x8005'
PidLidInstantMessagingAddress = 'PT_UNICODE:PSETID_Address:0x8062'
PidLidWorkAddressStreet = 'PT_UNICODE:PSETID_Address:0x8045'
PidLidWorkAddressCity = 'PT_UNICODE:PSETID_Address:0x8046'
PidLidWorkAddressState = 'PT_UNICODE:PSETID_Address:0x8047'
PidLidWorkAddressPostalCode = 'PT_UNICODE:PSETID_Address:0x8048'
PidLidWorkAddressCountry = 'PT_UNICODE:PSETID_Address:0x8049'

PidLidWebPage = 'PT_STRING8:PSETID_Address:0x802b'


def set_email_addresses(item, arg) -> None:  # TODO multiple via pyko
    item.address1 = '%s <%s>' % (arg[0]['name'], arg[0]['address'])


def _phys_address(addr) -> dict:
    data = {
        'street': addr.street,
        'city': addr.city,
        'postalCode': addr.postal_code,
        'state': addr.state,
        'countryOrRegion': addr.country
    }
    return {a: b for (a, b) in data.items() if b}


def _webpage(item) -> str:
    binary_string = item.get(PidLidWebPage)
    if binary_string:
        return binary_string.decode('UTF-8')
    else:
        return ''


PHYS_ADDRESS_KEY_STREET = 'street'
PHYS_ADDRESS_KEY_CITY = 'city'
PHYS_ADDRESS_KEY_POSTAL_CODE = 'postalCode'
PHYS_ADDRESS_KEY_STATE = 'state'
PHYS_ADDRESS_KEY_COUNTRY_OR_REGION = 'countryOrRegion'

PHYS_ADDRESS_HOME = 'PT_STRING8:PSETID_Address:0x801a'
PHYS_ADDRESS_BUSINESS = 'PT_STRING8:PSETID_Address:0x801b'
PHYS_ADDRESS_OTHER = 'PT_STRING8:PSETID_Address:0x801c'

PHYS_ADDRESS_DICT = {
    PHYS_ADDRESS_HOME: {
        PHYS_ADDRESS_KEY_STREET:            PR_HOME_ADDRESS_STREET_W,
        PHYS_ADDRESS_KEY_CITY:              PR_HOME_ADDRESS_CITY_W,
        PHYS_ADDRESS_KEY_POSTAL_CODE:       PR_HOME_ADDRESS_POSTAL_CODE_W,
        PHYS_ADDRESS_KEY_STATE:             PR_HOME_ADDRESS_STATE_OR_PROVINCE_W,
        PHYS_ADDRESS_KEY_COUNTRY_OR_REGION: PR_HOME_ADDRESS_COUNTRY_W,
    },
    PHYS_ADDRESS_BUSINESS: {
        PHYS_ADDRESS_KEY_STREET:            PidLidWorkAddressStreet,
        PHYS_ADDRESS_KEY_CITY:              PidLidWorkAddressCity,
        PHYS_ADDRESS_KEY_POSTAL_CODE:       PidLidWorkAddressPostalCode,
        PHYS_ADDRESS_KEY_STATE:             PidLidWorkAddressState,
        PHYS_ADDRESS_KEY_COUNTRY_OR_REGION: PidLidWorkAddressCountry,
    },
    PHYS_ADDRESS_OTHER: {
        PHYS_ADDRESS_KEY_STREET:            PR_OTHER_ADDRESS_STREET_W,
        PHYS_ADDRESS_KEY_CITY:              PR_OTHER_ADDRESS_CITY_W,
        PHYS_ADDRESS_KEY_POSTAL_CODE:       PR_OTHER_ADDRESS_POSTAL_CODE_W,
        PHYS_ADDRESS_KEY_STATE:             PR_OTHER_ADDRESS_STATE_OR_PROVINCE_W,
        PHYS_ADDRESS_KEY_COUNTRY_OR_REGION: PR_OTHER_ADDRESS_COUNTRY_W,
    },
}


def _set_phys_address(item, args: dict, prop_tag: str) -> None:
    try:
        is_args_list = True
        is_prop_tags_list = True
        if not isinstance(args, dict):
            logging.error("args is not a dict")
            is_args_list = False
        if not isinstance(prop_tag, str):
            logging.error("proptags is not a string")
            is_prop_tags_list = False
        if not is_args_list or not is_prop_tags_list:
            return
    except NameError:
        logging.exception('Parameter(s) not defined')
    addr_tags = PHYS_ADDRESS_DICT[prop_tag]
    for key, value in args.items():
        if key in addr_tags and isinstance(value, str):
            _set_value_by_tag(item, value, addr_tags[key])
    addr_byte_array = _create_addr_string(args).encode('UTF-8')
    _set_value_by_tag(item, addr_byte_array, prop_tag)


def _create_addr_string(address: dict) -> str:
    # Get number of address parts
    to_set = {}
    for key, value in address.items():
        if isinstance(value, str) and value:
            to_set[key] = value
    addr_parts_count = len(to_set)
    if addr_parts_count == 0:
        # Return empty string
        return ""
    elif addr_parts_count == 1:
        # Only one field set. Return it.
        return list(to_set.values())[0]
    else:
        addr_string = ""
        # Outlook(windows) uses CRLF as line ending
        # Kopano webapp is prepared for this
        line_separator = '\r\n'
        field_separator = ' '
        if PHYS_ADDRESS_KEY_STREET in to_set:
            addr_string += to_set[PHYS_ADDRESS_KEY_STREET]
            # Street is always on the first line
            addr_string += line_separator
        if PHYS_ADDRESS_KEY_CITY in to_set:
            addr_string += to_set[PHYS_ADDRESS_KEY_CITY]
        if PHYS_ADDRESS_KEY_STATE in to_set:
            if PHYS_ADDRESS_KEY_CITY in to_set:
                # City and state are separated by a whitespace
                addr_string += field_separator
            addr_string += to_set[PHYS_ADDRESS_KEY_STATE]
        if PHYS_ADDRESS_KEY_POSTAL_CODE in to_set:
            if PHYS_ADDRESS_KEY_CITY in to_set or PHYS_ADDRESS_KEY_STATE in to_set:
                # City and postal code or state and postal code are separated by a whitespace
                addr_string += field_separator
            addr_string += to_set[PHYS_ADDRESS_KEY_POSTAL_CODE]
        if PHYS_ADDRESS_KEY_COUNTRY_OR_REGION in to_set:
            # Country or region is always on the last line
            if not addr_string.endswith(line_separator):
                addr_string += line_separator
            addr_string += to_set[PHYS_ADDRESS_KEY_COUNTRY_OR_REGION]

        return addr_string


def _set_birthday(item, arg: str) -> None:
    if arg.endswith("Z"):
        arg = arg.replace("Z", "+0000")
    # TODO must end with + and 4 0's
    b_day = datetime.strptime(arg, '%Y-%m-%dT%H:%M:%S.%f%z')
    _set_value_by_tag(item, b_day, PR_BIRTHDAY)


class DeletedContactResource(ItemResource):
    fields = {
        '@odata.type': lambda item: '#microsoft.graph.contact',  # TODO
        'id': lambda item: item.entryid,
        '@removed': lambda item: {'reason': 'deleted'}  # TODO soft deletes
    }


@experimental
class ContactResource(ItemResource):
    fields = ItemResource.fields.copy()
    fields.update({
        'displayName': lambda item: item.name,
        'emailAddresses': lambda item: [{'name': a.name, 'address': a.email} for a in item.addresses()],
        'parentFolderId': lambda item: item.folder.entryid,
        'givenName': lambda item: item.first_name or None,
        'middleName': lambda item: item.middle_name or None,
        'surname': lambda item: item.last_name or None,
        'nickName': lambda item: item.nickname or None,
        'title': lambda item: item.title or None,
        'companyName': lambda item: item.company_name or None,
        'mobilePhone': lambda item: item.mobile_phone or None,
        'personalNotes': lambda item: item.text,
        'generation': lambda item: item.generation or None,
        'children': lambda item: item.children,
        'spouseName': lambda item: item.spouse or None,
        'birthday': lambda item: item.birthday and _date(item.birthday) or None,
        'initials': lambda item: item.initials or None,
        'yomiGivenName': lambda item: item.yomi_first_name or None,
        'yomiSurname': lambda item: item.yomi_last_name or None,
        'yomiCompanyName': lambda item: item.yomi_company_name or None,
        'fileAs': lambda item: item.file_as,
        'jobTitle': lambda item: item.job_title or None,
        'department': lambda item: item.department or None,
        'officeLocation': lambda item: item.office_location or None,
        'profession': lambda item: item.profession or None,
        'manager': lambda item: item.manager or None,
        'assistantName': lambda item: item.assistant or None,
        'businessHomePage': lambda item: _webpage(item) or None,
        'homePhones': lambda item: item.home_phones,
        'businessPhones': lambda item: item.business_phones,
        'imAddresses': lambda item: item.im_addresses,
        'homeAddress': lambda item: _phys_address(item.home_address),
        'businessAddress': lambda item: _phys_address(item.business_address),
        'otherAddress': lambda item: _phys_address(item.other_address),
    })

    set_fields = {
        'displayName': lambda item, arg: setattr(item, 'name', arg),
        'emailAddresses': set_email_addresses,
        'givenName': lambda item, arg: _set_value_by_tag(item, arg, PR_GIVEN_NAME_W),
        'middleName': lambda item, arg: _set_value_by_tag(item, arg, PR_MIDDLE_NAME_W),
        'surname': lambda item, arg: _set_value_by_tag(item, arg, PR_SURNAME_W),
        'nickName': lambda item, arg: _set_value_by_tag(item, arg, PR_NICKNAME_W),
        'title': lambda item, arg: _set_value_by_tag(item, arg, PR_DISPLAY_NAME_PREFIX_W),
        'companyName': lambda item, arg: _set_value_by_tag(item, arg, PR_COMPANY_NAME_W),
        'mobilePhone': lambda item, arg: _set_value_by_tag(item, arg, PR_MOBILE_TELEPHONE_NUMBER_W),
        'personalNotes': lambda item, arg: _set_value_by_tag(item, str(arg), PR_BODY_W),
        'generation': lambda item, arg: _set_value_by_tag(item, arg, PR_GENERATION_W),
        'children': lambda item, arg: _set_value_by_tag(item, arg, PR_CHILDRENS_NAMES_W),
        'spouseName': lambda item, arg: _set_value_by_tag(item, arg, PR_SPOUSE_NAME_W),
        'birthday': lambda item, arg: _set_birthday(item, arg),
        'initials': lambda item, arg: _set_value_by_tag(item, arg, PR_INITIALS_W),
        'yomiGivenName': lambda item, arg: _set_value_by_tag(item, arg, PidLidYomiFirstName),
        'yomiSurname': lambda item, arg: _set_value_by_tag(item, arg, PidLidYomiLastName),
        'yomiCompanyName': lambda item, arg: _set_value_by_tag(item, arg, PidLidYomiCompanyName),
        'fileAs': lambda item, arg: _set_value_by_tag(item, arg, PidLidFileUnder),
        'jobTitle': lambda item, arg: _set_value_by_tag(item, arg, PR_TITLE_W),
        'department': lambda item, arg: _set_value_by_tag(item, arg, PR_DEPARTMENT_NAME_W),
        'officeLocation': lambda item, arg: _set_value_by_tag(item, arg, PR_OFFICE_LOCATION_W),
        'profession': lambda item, arg: _set_value_by_tag(item, arg, PR_PROFESSION_W),
        'manager': lambda item, arg: _set_value_by_tag(item, arg, PR_MANAGER_NAME_W),
        'assistantName': lambda item, arg: _set_value_by_tag(item, arg, PR_ASSISTANT_W),
        'businessHomePage': lambda item, arg: _set_value_by_tag(item, arg.encode('UTF-8'), PidLidWebPage),
        'homePhones': lambda item, arg: _set_value_per_tag(item, arg, [PR_HOME_TELEPHONE_NUMBER_W,
                                                                       PR_HOME2_TELEPHONE_NUMBER_W]),
        'businessPhones': lambda item, arg: _set_value_per_tag(item, arg, [PR_BUSINESS_TELEPHONE_NUMBER_W,
                                                                           PR_BUSINESS2_TELEPHONE_NUMBER_W]),
        'imAddresses': lambda item, arg: _set_value_by_tag(item, ', '.join(arg), PidLidInstantMessagingAddress),
        'homeAddress': lambda item, arg: _set_phys_address(item, arg, PHYS_ADDRESS_HOME),
        'businessAddress': lambda item, arg: _set_phys_address(item, arg, PHYS_ADDRESS_BUSINESS),
        'otherAddress': lambda item, arg: _set_phys_address(item, arg, PHYS_ADDRESS_OTHER),
    }

    deleted_resource = DeletedContactResource

    def handle_get(self, req, resp, store, server, folderid, itemid):
        folder = _folder(store, folderid or 'contacts')  # TODO all folders?

        if itemid:
            if itemid == 'delta':
                self._handle_get_delta(req, resp, folder=folder)
            else:
                self._handle_get_with_itemid(req, resp, folder=folder, itemid=itemid)
        else:
            raise HTTPBadRequest("Missing contact itemid")

    def _handle_get_delta(self, req, resp, folder):
        req.context.deltaid = '{itemid}'
        self.delta(req, resp, folder)

    def _handle_get_with_itemid(self, req, resp, folder, itemid):
        data = _item(folder, itemid)
        self.respond(req, resp, data)

    def on_get(self, req, resp, userid=None, folderid=None, itemid=None, method=None):
        handler = None

        if not method:
            handler = self.handle_get
        else:
            raise HTTPBadRequest("Unsupported contact segment '%s'" % method)

        server, store, userid = _server_store(req, userid, self.options)
        handler(req, resp, store=store, server=server, folderid=folderid, itemid=itemid)

    def handle_patch(self, req, resp, store, folder, itemid):
        item = _item(folder, itemid)
        fields = self.load_json(req)

        for field, value in fields.items():
            if field in self.set_fields:
                self.set_fields[field](item, value)

        self.respond(req, resp, item, ContactResource.fields)

    def on_patch(self, req, resp, userid=None, folderid=None, itemid=None, method=None):
        handler = None

        if not method:
            handler = self.handle_patch

        else:
            raise HTTPBadRequest("Unsupported message segment '%s'" % method)

        server, store, userid = _server_store(req, userid, self.options)
        folder = _folder(store, folderid or 'contacts')  # TODO all folders?
        handler(req, resp, store=store, folder=folder, itemid=itemid)

    def handle_delete(self, req, resp, store, server, folderid, itemid):
        item = _item(store, itemid)

        store.delete(item)

        self.respond_204(resp)

    def on_delete(self, req, resp, userid=None, folderid=None, itemid=None):
        handler = self.handle_delete

        server, store, userid = _server_store(req, userid, self.options)
        handler(req, resp, store=store, server=server, folderid=folderid, itemid=itemid)
