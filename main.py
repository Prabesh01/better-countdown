

from flask import Flask, render_template, request, jsonify
from datetime import datetime, timedelta
import pytz
import json
from flask_httpauth import HTTPBasicAuth
from werkzeug.security import generate_password_hash, check_password_hash
import requests

app = Flask(__name__)
auth = HTTPBasicAuth()

import os
from dotenv import load_dotenv
load_dotenv()

TOKEN = os.environ.get("GITHUB_GIST_TOKEN")
gist_id = "10b4cd53f49dff9dd1b59e75716cadbb"


def fetch_gist(fname):
    url = f"https://api.github.com/gists/{gist_id}"
    headers = {
        "Authorization": f"token {TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        gist_data = response.json()
        content = gist_data["files"][fname]["content"]
        return json.loads(content)
    return None

def update_gist(content, fname="events.json"):
    url = f"https://api.github.com/gists/{gist_id}"
    headers = {
        "Authorization": f"token {TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    data = {
        "files": {
            fname: {
                "content": json.dumps(content, indent=2)
            }
        }
    }
    response = requests.patch(url, headers=headers, json=data)
    return response.json()

users = fetch_gist("users.json")
event_data = fetch_gist("events.json")

@auth.verify_password
def verify_password(username, password):
    global users
    if not username or not password:
        return False
    if username in users:
        if check_password_hash(users.get(username), password):
            return username
    else:
        users[username] = generate_password_hash(password)
        update_gist("users.json", users)
        return username
    return False


@app.route('/')
@auth.login_required
def index():
    global event_data
    user=auth.username()
    if not user in event_data:
        event_data[auth.username()] = []
        update_gist("events.json", event_data)

    events = event_data[user]
    upcoming_events = calculate_upcoming_events(events)

    # Get all unique tags
    all_tags = set()
    for event in events:
        if 'tags' in event:
            all_tags.update(event['tags'])

    unexpired_events = []
    for event in upcoming_events: unexpired_events.append(event['id'])
    for event in events:
        if not events.index(event) in unexpired_events:
            event_datetime_user = datetime.strptime(f"{event['date']} {event['start']}", "%Y-%m-%d %H:%M:%S")
            desc = ""
            if event["repeat"]:
                desc = f"Repeat {event['repeat']} "
                if "weekdays" in event:
                    desc += f'{len(event["weekdays"])} times and '
                else:
                    desc += f'and '
                if 'repeat_start' in event and 'repeat_end' in event:
                    desc += f"run from {event['repeat_start']} to {event['repeat_end']}"
                else:
                    desc += f"run from {event['start_at']} to {event['end_at']}"
                if 'skip' in event:
                    desc += f" , skip {len(event['skip'])} instances"
            upcoming_events.append({
                'id': events.index(event),
                'name': event['name'],
                'description': event['description'],
                'datetime': event_datetime_user,
                'timezone': event['timezone'],
                "tags": ["expired"],
                "desc": desc,
            })

    return render_template('index.html', upcoming_events=upcoming_events,all_tags=sorted(all_tags))


def calculate_upcoming_events(events):
    # Calculate upcoming events for countdown
    upcoming_events = []
    now = datetime.now(pytz.utc)
    for event in events:
        # For non-repeating events
        if not event.get('repeat'):
            event_datetime_user = datetime.strptime(f"{event['date']} {event['start']}", "%Y-%m-%d %H:%M:%S")
            event_datetime_utc = pytz.timezone(event['timezone']).localize(event_datetime_user).astimezone(pytz.utc)

            # Check if this instance is skipped
            if 'skip' in event and event['date'] in event['skip']:
                continue

            if event_datetime_utc > now:
                upcoming_events.append({
                    'id': events.index(event),
                    'name': event['name'].replace('{i}', '1'),
                    'description': event['description'],
                    'datetime': event_datetime_user,
                    'timezone': event['timezone'],
                    'plus': None,
                    'minus': None,
                    'instance_date': None,
                    "tags": event.get('tags', [])
                })
        else:
            # Handle repeating events
            repeat_type = event['repeat']
            start_date = datetime.strptime(event['date'], "%Y-%m-%d").date()

            if 'repeat_start' in event and 'repeat_end' in event:
                repeat_start = datetime.strptime(event['repeat_start'], "%Y-%m-%d").date()
                repeat_end = datetime.strptime(event['repeat_end'], "%Y-%m-%d").date()
            else:
                if repeat_type == 'weekly':
                    start_date_local = pytz.timezone(event['timezone']).localize(datetime.combine(start_date, datetime.strptime(event['start'], "%H:%M:%S").time()))
                    while start_date_local.weekday() not in event.get('weekdays', []):
                        start_date_local += timedelta(days=1)
                    start_date = start_date_local.date()
                repeat_start = start_date

                skip_dates=len(event.get('skip', []))
                total_events = (event['end_at'] - event['start_at'])+skip_dates
                if repeat_type == 'daily':
                    skip_days = total_events
                elif repeat_type == 'weekly':
                    skip_days = total_events * 7
                elif repeat_type == 'monthly':
                    skip_days = total_events * 32
                elif repeat_type == 'yearly':
                    skip_days = total_events * 366
                repeat_end = start_date + timedelta(days=skip_days)

            current_date = repeat_start
            i = event.get('start_at', 1)
            found_upcoming = False

            while current_date <= repeat_end and not found_upcoming:

                date_str = current_date.strftime('%Y-%m-%d')

                # Check if this instance is skipped
                if 'skip' in event and date_str in event['skip']:
                    # Move to next date without incrementing counter
                    if repeat_type == 'daily':
                        current_date += timedelta(days=1)
                    elif repeat_type == 'weekly':
                        current_date += timedelta(days=7)
                    elif repeat_type == 'monthly':
                        try:
                            current_date = current_date.replace(month=current_date.month + 1)
                        except ValueError:
                            if current_date.month == 12:
                                current_date = current_date.replace(year=current_date.year + 1, month=1)
                            else:
                                next_month = current_date.replace(day=28) + timedelta(days=4)
                                current_date = next_month - timedelta(days=next_month.day)
                    elif repeat_type == 'yearly':
                        current_date = current_date.replace(year=current_date.year + 1)
                    continue
                event_datetime_user = datetime.combine(current_date, datetime.strptime(event['start'], "%H:%M:%S").time())
                event_datetime_utc = pytz.timezone(event['timezone']).localize(event_datetime_user).astimezone(pytz.utc)

                plus=minus=True
                if 'repeat_start' in event:
                    if repeat_type == 'daily': diff = timedelta(days=1)
                    elif repeat_type == 'weekly': diff = timedelta(days=7)
                    elif repeat_type == 'monthly': diff = timedelta(months=1)
                    elif repeat_type == 'yearly': diff = timedelta(years=1)

                    repeat_start_date = datetime.strptime(event['repeat_start'], "%Y-%m-%d").date()
                    if  repeat_start_date >= current_date and (repeat_start_date + diff) <= current_date:
                        plus=False
                    if repeat_start_date <= current_date and (repeat_start_date + diff) >= current_date:
                        minus=False

                elif 'start_at' in event:
                    if event['start_at'] == event['end_at']:
                        plus=False

                if repeat_type == 'weekly' and current_date.weekday() in event.get('weekdays', []):
                    if event_datetime_utc > now:
                        upcoming_events.append({
                            'id': events.index(event),
                            'name': event['name'].replace('{i}', str(i)),
                            'description': event['description'],
                            'datetime': event_datetime_user,
                            'timezone': event['timezone'],
                            'plus': plus if '{i}' in event['name'] else False,
                            'minus': minus if '{i}' in event['name'] else False,
                            'instance_date': current_date.strftime('%Y-%m-%d'),
                            "tags": event.get('tags', [])
                        })
                        found_upcoming = True
                        # break
                    i += 1
                elif repeat_type in ['daily', 'monthly', 'yearly']:
                    if event_datetime_utc > now:
                        upcoming_events.append({
                            'id': events.index(event),
                            'name': event['name'].replace('{i}', str(i)),
                            'description': event['description'],
                            'datetime': event_datetime_user,
                            'timezone': event['timezone'],
                            'plus': plus if '{i}' in event['name'] else False,
                            'minus': minus if '{i}' in event['name'] else False,
                            'instance_date': current_date.strftime('%Y-%m-%d'),
                            "tags": event.get('tags', [])
                        })
                        found_upcoming = True
                        # break  # Only take the next instance
                    i += 1

                # Move to next date based on repeat type
                if repeat_type == 'daily':
                    current_date += timedelta(days=1)
                elif repeat_type == 'weekly':
                    current_date += timedelta(days=7)
                elif repeat_type == 'monthly':
                    # Move to same day next month (handles month length differences)
                    try:
                        current_date = current_date.replace(month=current_date.month + 1)
                    except ValueError:
                        if current_date.month == 12:
                            current_date = current_date.replace(year=current_date.year + 1, month=1)
                        else:
                            # Move to last day of next month if current day doesn't exist
                            next_month = current_date.replace(day=28) + timedelta(days=4)
                            current_date = next_month - timedelta(days=next_month.day)
                elif repeat_type == 'yearly':
                    current_date = current_date.replace(year=current_date.year + 1)

    upcoming_events.sort(key=lambda x: x['datetime'])
    return upcoming_events


@app.route('/add_event', methods=['POST'])
@auth.login_required
def add_event():
    global event_data
    data = request.json

    # Validate required fields
    if not data.get('name') or not data.get('date') or not data.get('timezone'):
        return jsonify({'error': 'Name, date, and timezone are required'}), 400

    # Set defaults
    event = {
        'name': data['name'],
        'date': data['date'],
        'start': data.get('start', '00:00:00'),
        'description': data.get('description', ''),
        'timezone': data['timezone'],
        'repeat': data.get('repeat'),
        'tags': data.get('tags', [])
    }

    # Handle repeating events
    if event['repeat']:
        if event['repeat'] == 'weekly':
            event['weekdays'] = data.get('weekdays', [])

        if 'repeat_start' in data and 'repeat_end' in data:
            event['repeat_start'] = data['repeat_start']
            event['repeat_end'] = data['repeat_end']
        elif 'start_at' in data and 'end_at' in data:
            event['start_at'] = data['start_at']
            event['end_at'] = data['end_at']
        else:
            return jsonify({'error': 'For repeating events, either repeat_start/repeat_end or start_at/end_at are required'}), 400

    event_data[auth.username()].append(event)
    update_gist(event_data)
    return jsonify({'message': 'Event added successfully'}), 200

@auth.login_required
@app.route('/delete_event/<int:event_id>', methods=['DELETE'])
def delete_event(event_id):
    global event_data
    events= event_data[auth.username()]
    if event_id < 0 or event_id >= len(events):
        return jsonify({'error': 'Invalid event ID'}), 404

    del events[event_id]
    update_gist(event_data)

    return jsonify({'message': 'Event deleted successfully'}), 200

@auth.login_required
@app.route('/skip_instance/<int:event_id>', methods=['POST'])
def skip_instance(event_id):
    global event_data
    events= event_data[auth.username()]
    if event_id < 0 or event_id >= len(events):
        return jsonify({'error': 'Invalid event ID'}), 404

    data = request.json
    if not data.get('date'):
        return jsonify({'error': 'Date is required to skip instance'}), 400

    event = events[event_id]
    if 'skip' not in event:
        event['skip'] = []

    if data['date'] not in event['skip']:
        event['skip'].append(data['date'])

    update_gist(event_data)

    return jsonify({'message': 'Instance skipped successfully'}), 200

@auth.login_required
@app.route('/alter_count/<int:event_id>', methods=['POST'])
def alter_count(event_id):
    global event_data
    events= event_data[auth.username()]
    if event_id < 0 or event_id >= len(events):
        return jsonify({'error': 'Invalid event ID'}), 404

    data = request.json
    if not data.get('count'):
        return jsonify({'error': 'Count is required to alter event counter'}), 400

    event = events[event_id]

    count= data['count']
    if 'start_at' in event:
        event['start_at'] += count
    elif  'repeat_start' in event:
        repeat_start = datetime.strptime(event['repeat_start'], "%Y-%m-%d").date()

        repeat_type = event['repeat']
        if repeat_type == 'daily': diff = timedelta(days=count)
        elif repeat_type == 'weekly': diff = timedelta(days=count*7)
        elif repeat_type == 'monthly': diff = timedelta(months=count)
        elif repeat_type == 'yearly': diff = timedelta(years=count)
        event['repeat_start'] = repeat_start - diff
        event['repeat_start'] = event['repeat_start'].strftime('%Y-%m-%d')

    update_gist(event_data)

    return jsonify({'message': 'Counter altered successfully'}), 200

@auth.login_required
@app.route('/update_description/<int:event_id>', methods=['POST'])
def update_description(event_id):
    global event_data
    events= event_data[auth.username()]
    if event_id < 0 or event_id >= len(events):
        return jsonify({'error': 'Invalid event ID'}), 404

    data = request.json
    if 'description' not in data:
        return jsonify({'error': 'Description is required'}), 400

    events[event_id]['description'] = data['description']

    update_gist(event_data)

    return jsonify({'message': 'Description updated successfully'}), 200


@auth.login_required
@app.route('/extend-event', methods=['POST'])
def extend_event():
    global event_data
    events= event_data[auth.username()]

    data = request.get_json()
    event_id = int(data['event_id'])
    hours = data['hours']

    if event_id < 0 or event_id >= len(events):
        return jsonify({'error': 'Invalid event ID'}), 404

    event = events[event_id]
    if not event['repeat']:
        new_datetime = datetime.now(pytz.utc) + timedelta(hours=hours)

        event_tz = pytz.timezone(event['timezone'])
        new_datetime_local = new_datetime.astimezone(event_tz)
        events[event_id]['date'] = new_datetime_local.strftime('%Y-%m-%d')
        events[event_id]['start'] = new_datetime_local.strftime('%H:%M:%S')
    else:
        if 'repeat_end' in event:
            repeat_end = datetime.strptime(event['repeat_end'], "%Y-%m-%d").date()
            repeat_end += timedelta(hours=hours)
            events[event_id]['repeat_end'] = repeat_end.strftime('%Y-%m-%d')
        else:
            end_at = event.get('end_at', 1)
            end_at += hours
            events[event_id]['end_at'] = end_at
    update_gist(event_data)
    return jsonify({'success': True})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=os.getenv("PORT", 5000), debug=True)
