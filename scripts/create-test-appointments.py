#!/usr/bin/python3

import argparse

from collections import namedtuple
from datetime import datetime, timedelta
from email.utils import formatdate
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase

import pytz
import kopano

from icalendar import Alarm, Calendar, Event, Timezone, TimezoneStandard, vCalAddress, vText


DATEFORMAT = '%Y-%m-%d'
BASEDATE = (datetime.utcnow()+timedelta(days=1)).strftime(DATEFORMAT)

OrganiserTuple = namedtuple('Organiser', ['fullname', 'email'])


def create_simple_event(basedate):
    event = Event()
    event.add('summary', 'Simple event')
    event.add('description', 'This is a simple meeting generated by an awesome script')
    event.add('uid', "simple-event-1")
    event.add('location', "Delft")

    start = basedate.replace(hour=12, minute=0)
    end = start + timedelta(hours=1)

    event.add('dtstart', start)
    event.add('dtend', end)
    event.add('dtstamp', basedate)

    alarm = Alarm()
    alarm.add('trigger', timedelta(minutes=-5))
    alarm.add('action', 'display')
    alarm.add('description', 'meeting coming up in 5 minutes')
    event.add_component(alarm)

    return event


def create_simple_allday_event(basedate):
    event = Event()
    event.add('summary', 'Simple all day event')
    event.add('description', 'This is a simple all day meeting generated by an awesome script')
    event.add('uid', "simple-allday-event-1")
    event.add('location', "Delft")

    start = basedate.replace(hour=0, minute=0)
    end = start + timedelta(days=1)

    event.add('dtstart', start)
    event.add('dtend', end)
    event.add('dtstamp', basedate)
    event.add('X-MICROSOFT-CDO-ALLDAYEVENT', 'TRUE')

    return event


def create_meetingrequest(basedate, user, organiser):
    event = Event()
    event.add('summary', 'Simple Meeting Request invite')
    event.add('description', 'This is a simple meeting request generated by an awesome script')
    event.add('uid', "meetingrequest-event-1")
    event.add('location', "Hamburg")

    start = basedate.replace(hour=10, minute=0)
    end = start + timedelta(hours=1)

    event.add('dtstart', start)
    event.add('dtend', end)
    event.add('dtstamp', basedate)
    event.add('priority', 5)
    event.add('status', 'CONFIRMED')
    event.add('transp', 'OPAQUE')
    event.add('sequence', 1)

    # Organiser
    vcalorg = vCalAddress('MAILTO:{}'.format(organiser.email))
    vcalorg.params['cn'] = vText(organiser.fullname)
    vcalorg.params['role'] = vText('CHAIR')

    event['organizer'] = vcalorg

    # Attendee
    attendee = vCalAddress('MAILTO:{}'.format(user.email))
    attendee.params['cn'] = vText(user.fullname)
    attendee.params['ROLE'] = vText('REQ-PARTICIPANT')
    attendee.params['PARTSTAT'] = vText('NEEDS-ACTION')
    attendee.params['RSVP'] = vText('TRUE')
    event.add('attendee', attendee, encode=0)

    return event


def main(user, organiser, basedate):
    user.calendar.empty()

    # Create simple event
    vcal = Calendar()
    vcal.add('prodid', 'Kopano ICS Generator')
    vcal.add('version', '2.0')

    vcal.add_component(create_simple_event(basedate))
    vcal.add_component(create_simple_allday_event(basedate))

    user.calendar.read_ics(vcal.to_ical())

    # Meeting requests
    vcal = Calendar()
    vcal.add('prodid', 'Kopano ICS Generator')
    vcal.add('version', '2.0')
    vcal.add('method', 'REQUEST')

    vcal.add_component(create_meetingrequest(basedate, user, organiser))

    msg = MIMEMultipart('alternative')
    msg['Date'] = formatdate(localtime=True)
    msg['Subject'] = 'Meeting request invite'
    msg['From'] = organiser.email
    msg['To'] = user.email
    msg.add_header('Content-class', 'urn:content-classes:calendarmessage')

    msg.attach(MIMEText("See attachement for Meeting Invite."))
    icspart = MIMEBase('text', 'calendar', **{'method': 'REQUEST', 'name': 'meeting.ics'})
    icspart.set_payload(vcal.to_ical())
    icspart.add_header('Content-Transfer-Encoding', '8bit')
    icspart.add_header('Content-class', 'urn:content-classes:calendarmessage')
    msg.attach(icspart)

    # TODO: import as own user, works when done by kopano-dagent, bug in pyko
    item = user.inbox.create_item(eml=msg.as_bytes())

    # Tentative accept in meeting request, normally done by dagent
    item.meetingrequest.accept(tentative=True, response=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Create test appointments in the specified users calendar')
    parser.add_argument('--user', type=str, help='The user to import appointments (kopano user)', required=True)
    parser.add_argument('--organiser', type=str, help='The Kopano user organiser')
    parser.add_argument('--basedate', type=str, help='The base date for the calendar default({})'.format(BASEDATE),
                        default=BASEDATE)
    args = parser.parse_args()

    basedate = datetime.strptime(args.basedate, DATEFORMAT)
    server = kopano.server()
    user = server.user(args.user)

    if args.organiser:
        orguser = server.user(args.organiser)
        organiser = OrganiserTuple(orguser.fullname, orguser.email)
    else:
        organiser = OrganiserTuple("Example Organiser", "organiser@example.com")

    main(user, organiser, basedate)