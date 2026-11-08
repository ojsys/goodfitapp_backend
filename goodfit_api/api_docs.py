"""
Interactive API docs (Swagger UI at /docs/, ReDoc at /redoc/).

Most endpoints are hand-written APIViews that read request.data directly, so
the generator can't see their request bodies. This module fills the gaps
in one place instead of decorating every view:

- TAGS: groups shown in the docs, in reading order, by URL prefix
- BODIES: request bodies for endpoints without a serializer
- AgfAutoSchema / AgfSchemaGenerator: apply both, and use JWT "Bearer" auth
"""

import re

from drf_yasg import openapi
from drf_yasg.generators import OpenAPISchemaGenerator
from drf_yasg.inspectors import SwaggerAutoSchema
from rest_framework.permissions import AllowAny

S, I, N, B, A, O = (openapi.TYPE_STRING, openapi.TYPE_INTEGER, openapi.TYPE_NUMBER,
                    openapi.TYPE_BOOLEAN, openapi.TYPE_ARRAY, openapi.TYPE_OBJECT)

DESCRIPTION = """
The API behind **A Good Fit**, the community wellness app from GoodCo Bike Club: rides, runs, walks and classes, the clubs and people around them, and the chats that keep a group ride together.

### Signing in
1. `POST /api/auth/login/` (or Apple / Google) returns `tokens.access` and `tokens.refresh`.
2. Click **Authorize** and paste `Bearer <access token>`.
3. When the access token expires, `POST /api/auth/token/refresh/` with the refresh token.

New accounts finish the age check (21+) and community guidelines before member endpoints open up. Until then they answer `403` with a `next_step`.

### Conventions
- JSON in, JSON out. Times are ISO 8601 in UTC; distances in meters, durations in seconds.
- Errors look like `{"code": "slow_mode", "message": "…"}` with a matching HTTP status.
- Lists that grow use cursors such as `?before=<id>` / `?after=<id>`.
- Rate limits: sign-in 30/hour, messages 120/hour, reports 20/hour (`429` when exceeded).
"""

# (prefix regex, tag). First match wins.
TAG_RULES = [
    (r'^/api/(health/)?$', 'Status'),
    (r'^/api/auth/(login|register|signup|apple|google|google-login|logout|token|password)/', 'Sign-in & accounts'),
    (r'^/api/auth/', 'Profile & settings'),
    (r'^/api/social/(home|feed|checklist|crew)/', 'Home & feed'),
    (r'^/api/social/(posts|comments|[^/]+/\{id\}/(comments|props))', 'Posts, comments & props'),
    (r'^/api/social/\{kind\}/', 'Posts, comments & props'),
    (r'^/api/social/people/', 'People'),
    (r'^/api/activities/(live|summaries)/', 'Legacy · live tracking'),
    (r'^/api/activities/', 'Activities'),
    (r'^/api/routes/', 'Routes'),
    (r'^/api/social/(community|clubs)/', 'Clubs & community'),
    (r'^/api/social/events/', 'Events & rides'),
    (r'^/api/events/', 'Events & rides'),
    (r'^/api/social/(buddies|me/location)/', 'Fit Buddies'),
    (r'^/api/social/privacy-zones/', 'Privacy'),
    (r'^/api/chats/', 'Chats'),
    (r'^/api/safety/', 'Safety'),
    (r'^/api/matching/', 'A Good Match (early)'),
    (r'^/api/messaging/', 'Legacy · messaging'),
]

TAGS = [
    ('Status', 'Is the API up?'),
    ('Sign-in & accounts', 'Email, Apple and Google sign-in, sign-up with the 21+ age check, tokens and passwords.'),
    ('Profile & settings', 'Your profile, onboarding answers, preferences and goals.'),
    ('Home & feed', 'The Home screen in one call, the feed, and the new-member checklist.'),
    ('Activities', 'Record and save a ride, run or class; activity details, photos and stats. '
                   'Saving is idempotent on `client_id`, so a retried upload never duplicates.'),
    ('Routes', 'Draw a route (snapped to roads and paths, with elevation), browse and save routes.'),
    ('Posts, comments & props', 'Posts with audience controls, comments, and props (kudos) on posts and activities.'),
    ('People', 'Follow and wave.'),
    ('Clubs & community', 'The Community hub, club pages, members and leaderboards.'),
    ('Events & rides', 'Browse rides by day, RSVP, and host a community ride (Plus) or suggest one to a club.'),
    ('Fit Buddies', 'People nearby who move like you. Locations are rounded to about 1 km.'),
    ('Privacy', 'Privacy zones and hidden track ends. Tracks are trimmed on the server before anyone else sees them.'),
    ('Chats', 'Ride chats open on RSVP and close 48 hours after the ride; direct messages. '
              'Poll `GET /messages/?after=<id>` for new ones. Slow mode answers `429` with `locked_until`.'),
    ('Safety', 'Report a person, post, activity, comment or message; block (two-way, everywhere); hide with Undo; '
               'Your reports. Unsafe reports are reviewed first, then under 21.'),
    ('A Good Match (early)', 'The opt-in dating space. Being rebuilt; expect changes.'),
    ('Legacy · live tracking', 'Older server-side tracking. New clients record on the phone and save with `POST /api/activities/record/`.'),
    ('Legacy · messaging', 'Older 1:1 conversations, kept for old app versions. Use Chats.'),
]


def tag_for(path):
    for rule, tag in TAG_RULES:
        if re.match(rule, path):
            return tag
    return 'Other'


def obj(props, required=(), example=None):
    return openapi.Schema(type=O, properties=props, required=list(required), example=example)


def s(desc='', **kw):
    return openapi.Schema(type=S, description=desc, **kw)


def i(desc='', **kw):
    return openapi.Schema(type=I, description=desc, **kw)


def n(desc='', **kw):
    return openapi.Schema(type=N, description=desc, **kw)


def b(desc='', **kw):
    return openapi.Schema(type=B, description=desc, **kw)


def arr(items, desc=''):
    return openapi.Schema(type=A, items=items, description=desc)


LATLNG = arr(arr(openapi.Schema(type=N)), 'Points as [latitude, longitude]')
VISIBILITY = s('Who can see it', enum=['everyone', 'followers', 'club', 'me'])
TZ = s('IANA time zone, e.g. America/New_York')

# (method, path) -> (summary, schema, multipart file fields)
BODIES = {
    ('post', '/api/auth/login/'): ('Sign in with email', obj({
        'email': s(format='email'), 'password': s(format='password')}, ['email', 'password'],
        {'email': 'shari@example.com', 'password': '••••••••'}), ()),
    ('post', '/api/auth/register/'): ('Create an account', obj({
        'full_name': s(), 'email': s(format='email'), 'password': s('At least 8 characters', format='password'),
        'birthday': s('YYYY-MM-DD. Must be 21 or older.', format='date'), 'timezone': TZ},
        ['full_name', 'email', 'password', 'birthday']), ()),
    ('post', '/api/auth/apple/'): ('Sign in with Apple', obj({
        'identity_token': s('From Sign in with Apple on the device'),
        'first_name': s('Apple only sends the name the first time'), 'last_name': s(), 'timezone': TZ},
        ['identity_token']), ()),
    ('post', '/api/auth/google/'): ('Sign in with Google', obj({
        'id_token': s('Google ID token from the device'), 'first_name': s(), 'last_name': s(), 'timezone': TZ},
        ['id_token']), ()),
    ('post', '/api/auth/google-login/'): ('Sign in with Google (older path)', obj({
        'id_token': s(), 'first_name': s(), 'last_name': s(), 'timezone': TZ}, ['id_token']), ()),
    ('post', '/api/auth/logout/'): ('Sign out', obj({'refresh_token': s('Revoked so it can’t be used again')},
                                                     ['refresh_token']), ()),
    ('post', '/api/auth/signup/birthday/'): ('Age check (21+)', obj({
        'month': i(minimum=1, maximum=12), 'day': i(minimum=1, maximum=31), 'year': i(), 'timezone': TZ},
        ['month', 'day', 'year'], {'month': 4, 'day': 12, 'year': 1994}), ()),
    ('patch', '/api/auth/onboarding/'): ('Save onboarding answers', obj({
        'intents': arr(s(), 'What brings you here'), 'interests': arr(s(), 'Activities you’re into'),
        'photo_step_done': b()}), ()),
    ('post', '/api/auth/onboarding/guidelines/'): ('Agree to the community guidelines', obj({
        'agreed': b('Must be true')}, ['agreed'], {'agreed': True}), ()),
    ('post', '/api/auth/password/change/'): ('Change password', obj({
        'old_password': s(format='password'), 'new_password': s('At least 8 characters', format='password')},
        ['old_password', 'new_password']), ()),
    ('post', '/api/auth/password/reset/'): ('Email a password reset link', obj({'email': s(format='email')},
                                                                               ['email']), ()),
    ('post', '/api/auth/profile/avatar/'): ('Upload a profile photo', None, ('avatar',)),
    ('post', '/api/auth/status/'): ('Set online status', obj({'status': s(enum=['online', 'offline', 'away'])}), ()),

    ('post', '/api/activities/record/'): ('Save a recorded activity', obj({
        'client_id': s('Unique per recording; a retry with the same id returns the saved activity'),
        'type': s(enum=['ride', 'run', 'walk', 'hike', 'yoga', 'strength', 'pilates', 'hiit', 'crossfit', 'swim']),
        'title': s(), 'start_time': s(format='date-time'),
        'moving_time': i('Seconds'), 'elapsed_time': i('Seconds'), 'distance': n('Meters'),
        'elevation_gain': n('Meters'), 'max_speed': n('m/s'), 'calories': i(),
        'effort': i('1 (easy) to 5 (all out)', minimum=1, maximum=5),
        'track': arr(arr(openapi.Schema(type=N)), 'GPS points as [lat, lng, time_offset_s, elevation_m]'),
        'laps': arr(obj({}), 'Optional laps'), 'visibility': VISIBILITY, 'club': i('Share with a club'),
        'route': i('Route followed, if any'), 'route_name': s()},
        ['client_id', 'type', 'start_time', 'moving_time']), ()),
    ('patch', '/api/activities/{id}/detail/'): ('Edit an activity', obj({
        'title': s(), 'effort': i(minimum=1, maximum=5), 'visibility': VISIBILITY, 'club': i()}), ()),
    ('post', '/api/activities/{id}/photos/'): ('Add a photo to an activity', None, ('image',)),
    ('post', '/api/activities/summaries/update/'): ('Update today’s totals (legacy)', obj({
        'total_steps': i(), 'total_distance': n(), 'total_calories': i(), 'total_active_minutes': i(),
        'total_workouts': i()}), ()),

    ('post', '/api/routes/'): ('Save a route', obj({
        'name': s(), 'line': LATLNG, 'waypoints': LATLNG, 'is_loop': b(),
        'best_for': s('Profile used for snapping', enum=['ride', 'run', 'walk']),
        'visibility': s(enum=['everyone', 'club', 'me']), 'club': i()}, ['name', 'line']), ()),
    ('post', '/api/routes/snap/'): ('Snap waypoints to roads and paths', obj({
        'waypoints': LATLNG, 'best_for': s(enum=['ride', 'run', 'walk']), 'is_loop': b(),
        'elevation': b('Also return the elevation gain')}, ['waypoints'],
        {'waypoints': [[40.6602, -73.9690], [40.6551, -73.9712]], 'best_for': 'ride', 'elevation': True}), ()),
    ('post', '/api/routes/{id}/save/'): ('Save a route to your list', None, ()),

    ('post', '/api/social/posts/'): ('Write a post', obj({
        'text': s(), 'type': s(enum=['post', 'intro']), 'mood': s(),
        'audience': s(enum=['everyone', 'followers', 'club']), 'club': i(),
        'tagged': arr(i(), 'People to tag'), 'is_intro': b()}, ['text']), ('photo',)),
    ('post', '/api/social/{kind}/{id}/comments/'): ('Comment', obj({'text': s()}, ['text']), ()),
    ('post', '/api/social/{kind}/{id}/props/'): ('Give props', None, ()),
    ('patch', '/api/social/checklist/'): ('Hide the new-member checklist', obj({'hidden': b()}, ['hidden']), ()),
    ('post', '/api/social/people/{id}/follow/'): ('Follow', None, ()),
    ('post', '/api/social/people/{id}/wave/'): ('Wave', None, ()),
    ('post', '/api/social/clubs/{id}/join/'): ('Join a club', None, ()),
    ('post', '/api/social/events/host/'): ('Host a ride or suggest one to a club', obj({
        'mode': s('community: publish now (Plus). suggest: send to a club’s team.', enum=['community', 'suggest']),
        'title': s(), 'activity_type': s(enum=['ride', 'run', 'walk', 'yoga']),
        'date': s(format='date'), 'time': s('HH:MM, local time'), 'meeting_spot': s(),
        'route': i(), 'pace': s(enum=['social', 'steady', 'brisk', 'fast']), 'no_drop': b(),
        'capacity': i(minimum=2, maximum=60), 'who_can_join': s(enum=['anyone', 'club', 'invite']),
        'club': i('Required for suggest or club-only rides'), 'note': s('For the club team'),
        'agree': b('Accept the host agreement (first time only)')},
        ['mode', 'title', 'date', 'time', 'meeting_spot']), ()),
    ('post', '/api/social/buddies/{id}/hide/'): ('Not interested', None, ()),
    ('post', '/api/social/buddies/{id}/invite/'): ('Invite to a ride you’re going to', obj({'event': i()},
                                                                                           ['event']), ()),
    ('patch', '/api/social/me/location/'): ('Set your approximate location', obj({
        'latitude': n(), 'longitude': n()}, ['latitude', 'longitude']), ()),
    ('post', '/api/social/privacy-zones/'): ('Add a privacy zone', obj({
        'label': s('e.g. Home'), 'latitude': n(), 'longitude': n(),
        'radius_m': i('Meters', minimum=100, maximum=1000)}, ['latitude', 'longitude']), ()),
    ('patch', '/api/social/privacy-zones/'): ('Hide the start and end of every track', obj({
        'hide_track_ends': b()}, ['hide_track_ends']), ()),

    ('post', '/api/chats/direct/'): ('Open a direct chat', obj({'user': i('Member id')}, ['user']), ()),
    ('post', '/api/chats/{id}/messages/'): ('Send a message', obj({
        'client_id': s('Unique per message; resending the same id never duplicates'),
        'body': s(), 'attachment': s(enum=['', 'route', 'photo', 'location']), 'route': i(),
        'latitude': n(), 'longitude': n(),
        'live_minutes': i('Share live location for 15, 30 or 60 minutes', enum=[15, 30, 60])},
        example={'client_id': '7f3a9c', 'body': 'See you there'}), ('photo',)),
    ('post', '/api/chats/{id}/read/'): ('Mark read', obj({'last_id': i('Newest message you’ve seen')},
                                                         ['last_id']), ()),
    ('patch', '/api/chats/messages/{id}/location/'): ('Update or stop a live location', obj({
        'latitude': n(), 'longitude': n(), 'stop': b('End sharing now')}), ()),

    ('post', '/api/safety/reports/'): ('Report something', obj({
        'target_kind': s(enum=['member', 'post', 'activity', 'comment', 'message']),
        'target_id': i('Member id, or the post / activity / comment / message id'),
        'reason': s('member: fake, under21, harassment, unsafe, other. '
                    'Everything else: spam, harassment, unsafe, inappropriate, other.',
                    enum=['spam', 'harassment', 'unsafe', 'inappropriate', 'fake', 'under21', 'other']),
        'details': s('Required when reason is other'), 'block': b('Also block them'),
        'context': s('Where it was seen, e.g. "Fit Buddies profile"')},
        ['target_kind', 'target_id', 'reason'],
        {'target_kind': 'post', 'target_id': 42, 'reason': 'spam', 'block': False}), ()),
    ('post', '/api/safety/hide/{kind}/{id}/'): ('Hide a post or activity, or someone from suggestions', None, ()),
    ('post', '/api/safety/blocks/{id}/'): ('Block', None, ()),
}


class AgfAutoSchema(SwaggerAutoSchema):
    def _entry(self):
        return BODIES.get((self.method.lower(), self.path))

    def get_tags(self, operation_keys=None):
        return [tag_for(self.path)]

    def get_summary_and_description(self):
        summary, description = super().get_summary_and_description()
        e = self._entry()
        if e:
            summary = e[0]
        return summary, description

    def get_consumes(self):
        e = self._entry()
        if e and e[2]:
            return ['multipart/form-data']
        return super().get_consumes()

    def get_request_body_parameters(self, consumes):
        e = self._entry()
        if not e:
            return super().get_request_body_parameters(consumes)
        _, schema, files = e
        if files:
            params = [openapi.Parameter(f, openapi.IN_FORM, type=openapi.TYPE_FILE, required=not schema)
                      for f in files]
            for name, prop in ((schema.properties or {}).items() if schema else ()):
                ptype = prop.type if prop.type in (S, I, N, B) else S
                params.append(openapi.Parameter(name, openapi.IN_FORM, type=ptype, description=prop.get(
                    'description', ''), required=name in (schema.required or [])))
            return params
        if schema is None:
            return []
        return [openapi.Parameter('data', openapi.IN_BODY, schema=schema, required=True)]

    def get_security(self):
        perms = getattr(self.view, 'permission_classes', ())
        if not perms or any(p is AllowAny for p in perms):
            return []
        return super().get_security()


class AgfSchemaGenerator(OpenAPISchemaGenerator):
    def get_schema(self, request=None, public=False):
        schema = super().get_schema(request, public)
        used = {t for p in schema.paths.values() for op in p.values()
                if isinstance(op, dict) for t in op.get('tags', [])}
        schema['tags'] = [{'name': n, 'description': d} for n, d in TAGS if n in used]
        return schema


INFO = openapi.Info(title='A Good Fit API', default_version='v1', description=DESCRIPTION)


# Branded pages: same drf-yasg templates, with the A Good Fit header and theme.
from drf_yasg.renderers import ReDocRenderer, SwaggerUIRenderer  # noqa: E402

SwaggerUIRenderer.template = 'docs/swagger-ui.html'
ReDocRenderer.template = 'docs/redoc.html'
