

from flask import Flask, render_template, request, jsonify
from datetime import datetime, timedelta
import pytz
import json

app = Flask(__name__)

events = []
try:
    with open('events.json', 'r') as f:
        events = json.load(f)
except: pass

@app.route('/')
def index():
    upcoming_events = calculate_upcoming_events()

    # Get all unique tags
    all_tags = set()
    for event in events:
        if 'tags' in event:
            all_tags.update(event['tags'])

    # Get filter from query parameter
    filter_tag = request.args.get('filter', 'all')

    # Filter events if needed
    if filter_tag != 'all':
        if filter_tag == 'none':
            filtered_events = [e for e in upcoming_events if 'tags' not in events[e['id']] or not events[e['id']]['tags']]
        else:
            filtered_events = [e for e in upcoming_events if 'tags' in events[e['id']] and filter_tag in events[e['id']]['tags']]
    else:
        filtered_events = upcoming_events

    return render_template('index.html', upcoming_events=filtered_events,all_tags=sorted(all_tags), current_filter=filter_tag)


def calculate_upcoming_events():
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
def add_event():
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

    events.append(event)
    with open('events.json', 'w') as f:
        json.dump(events, f, indent=4)
    return jsonify({'message': 'Event added successfully'}), 200


@app.route('/delete_event/<int:event_id>', methods=['DELETE'])
def delete_event(event_id):
    if event_id < 0 or event_id >= len(events):
        return jsonify({'error': 'Invalid event ID'}), 404

    del events[event_id]

    with open('events.json', 'w') as f:
        json.dump(events, f, indent=4)

    return jsonify({'message': 'Event deleted successfully'}), 200

@app.route('/skip_instance/<int:event_id>', methods=['POST'])
def skip_instance(event_id):
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

    with open('events.json', 'w') as f:
        json.dump(events, f, indent=4)

    return jsonify({'message': 'Instance skipped successfully'}), 200

@app.route('/alter_count/<int:event_id>', methods=['POST'])
def alter_count(event_id):
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

    with open('events.json', 'w') as f:
        json.dump(events, f, indent=4)

    return jsonify({'message': 'Counter altered successfully'}), 200

@app.route('/update_description/<int:event_id>', methods=['POST'])
def update_description(event_id):
    if event_id < 0 or event_id >= len(events):
        return jsonify({'error': 'Invalid event ID'}), 404

    data = request.json
    if 'description' not in data:
        return jsonify({'error': 'Description is required'}), 400

    events[event_id]['description'] = data['description']

    with open('events.json', 'w') as f:
        json.dump(events, f, indent=4)

    return jsonify({'message': 'Description updated successfully'}), 200

if __name__ == '__main__':
    app.run(debug=True)
