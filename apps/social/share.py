"""
Share sheet (link, Send, Story card, QR, More) and public link pages.

GET   /api/share/<kind>/<id>/          the card for the sheet
PATCH /api/share/activity/<id>/        {public: true}: anyone with the link can open it
GET   /api/share/recipients/?kind=     people (and ride chats, for rides/routes/activities) to Send to
POST  /api/share/send/                 {kind, id, users: [...], chats: [...], note}

kind: profile | club | club_invite | event | activity | route | segment

Public pages (no sign-in): /u/<id>  /c/<id>  /join/<club>-<member>-<code>  /e/<id>  /a/<id>  /r/<id>  /s/<id>
"""

import hashlib
import hmac

from django.conf import settings
from django.http import Http404
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.activities.models import Activity
from apps.events.models import Event
from apps.routes.models import Route
from apps.safety.visibility import blocked_ids, is_blocked
from apps.users.age_gate import safe_zone
from apps.users.models import User

from .feed import person
from .models import Club, ClubMembership
from .privacy import can_view_activity, public_track, sample

MI, FT = 1609.344, 3.28084
CLAY, OLIVE, GOLD = '#A65F2E', '#6E8046', '#7D6224'
NOUN = {'ride': 'ride', 'run': 'run', 'walk': 'walk', 'hike': 'hike', 'swim': 'swim'}


def base():
    return settings.SHARE_BASE_URL.rstrip('/')


def _bad(code, message, http=status.HTTP_400_BAD_REQUEST):
    return Response({'code': code, 'message': message}, status=http)


# ---------------------------------------------------------------- format

def dist(m, units):
    if not m:
        return ''
    return f'{m / 1000:.1f} km' if units == 'km' else f'{m / MI:.1f} mi'


def climb(m, units):
    if m is None:
        return ''
    return f'{round(m):,} m' if units == 'km' else f'{round(m * FT):,} ft'


def clock(sec):
    sec = int(sec or 0)
    h, m, s = sec // 3600, sec % 3600 // 60, sec % 60
    return f'{h}:{m:02d}:{s:02d}' if h else f'{m}:{s:02d}'


def initials(text):
    words = [w for w in text.replace('-', ' ').split() if w[:1].isalnum()]
    return ''.join(w[0] for w in words[:2]).upper() or text[:2].upper()


def invite_code(club_id, user_id):
    mac = hmac.new(settings.SECRET_KEY.encode(), f'join:{club_id}:{user_id}'.encode(), hashlib.sha256)
    return f'{club_id}-{user_id}-{mac.hexdigest()[:8]}'


def check_invite(code):
    try:
        club_id, user_id, _ = code.split('-')
        club_id, user_id = int(club_id), int(user_id)
    except ValueError:
        return None
    return (club_id, user_id) if hmac.compare_digest(invite_code(club_id, user_id), code) else None


def _when(e, tz):
    t = e.start_time.astimezone(tz)
    return f'{t:%a %b} {t.day} · {t:%-I:%M %p}'


# ------------------------------------------------------------------ cards

def card(kind, pk, viewer, request=None):
    """Everything the share sheet shows. Raises Http404 for things the
    viewer can't see."""
    units = viewer.units
    tz = safe_zone(viewer.timezone)
    if kind == 'profile':
        u = get_object_or_404(User, pk=pk, is_active=True)
        if is_blocked(viewer, u.id):
            raise Http404
        p = person(u, request)
        me = u.id == viewer.id
        return dict(kind=kind, id=u.id, heading='Share your profile' if me else f'Share {p["first_name"]}’s profile',
                    title=p['name'], sub=' · '.join(x for x in [u.neighborhood, u.headline] if x),
                    url=f'{base()}/u/{u.id}', thumb=p['initials'], thumb_bg=OLIVE, photo=p['photo'],
                    vis=('Anyone with the link can see your public profile' if me
                         else 'Anyone with the link can see their public profile'),
                    chats=False, can_public=False, public=False, qr_label=f'Scan to follow {p["first_name"]}',
                    story=None, link=f'/people/{u.id}')
    if kind in ('club', 'club_invite'):
        c = get_object_or_404(Club, pk=pk)
        members = c.memberships.count()
        place = c.location or c.neighborhood
        if kind == 'club_invite':
            if not ClubMembership.objects.filter(club=c, user=viewer).exists():
                raise Http404
            return dict(kind=kind, id=c.id, heading=f'Invite to {c.name}', title=c.name,
                        sub='Your invite drops friends right onto the club page',
                        url=f'{base()}/join/{invite_code(c.id, viewer.id)}', thumb=c.initials, thumb_bg=c.color,
                        vis='Anyone with this invite can join', chats=False, can_public=False, public=False,
                        qr_label=f'Scan to join {c.name}', story=None, link=f'/clubs/{c.id}')
        return dict(kind=kind, id=c.id, heading=f'Share {c.name}', title=c.name,
                    sub=' · '.join(x for x in [f'{members:,} member{"s" if members != 1 else ""}', place] if x),
                    url=f'{base()}/c/{c.id}', thumb=c.initials, thumb_bg=c.color,
                    vis='Anyone with the link can see the club page', chats=False, can_public=False, public=False,
                    qr_label=f'Scan to see {c.name}', story=None, link=f'/clubs/{c.id}')
    if kind == 'event':
        e = get_object_or_404(Event, pk=pk, is_active=True)
        host = e.club.name if e.club_id else (e.host_label or person(e.host, request)['name'])
        bits = [host, _when(e, tz), dist(e.distance_m, units)]
        return dict(kind=kind, id=e.id, heading='Invite friends to this', title=e.title,
                    sub=' · '.join(b for b in bits if b), url=f'{base()}/e/{e.id}', thumb=initials(e.title),
                    thumb_bg=CLAY, vis='Anyone with the link can see it and RSVP', chats=True, can_public=False,
                    public=False, qr_label='Scan to RSVP', story=None, link=f'/events/{e.id}')
    if kind == 'activity':
        a = get_object_or_404(Activity.objects.select_related('user', 'club'), pk=pk)
        if not can_view_activity(viewer, a):
            raise Http404
        mine = a.user_id == viewer.id
        noun = NOUN.get(a.type, 'workout')
        if a.visibility == 'everyone' or a.link_public:
            vis = 'Anyone with the link can open this'
        else:
            vis = {'followers': f'Only {"your" if mine else "their"} followers can open this link',
                   'club': f'Only {a.club.name if a.club_id else "club"} members can open this link',
                   'me': 'Only you can open this link'}.get(a.visibility, '')
        stats = [('Distance', dist(a.distance, units)) if a.distance else None,
                 ('Time', clock(a.moving_time or (a.duration or 0) * 60)),
                 ('Elev Gain', climb(a.elevation_gain, units)) if a.distance else None]
        stats = [s for s in stats if s][:3]
        line = sample(public_track(a.track_points(), a.user) if not mine else a.track_points(), 160) \
            if getattr(a, 'is_gps', False) else []
        return dict(kind=kind, id=a.id, heading=f'Share this {noun}', title=a.title,
                    sub=' · '.join(v for _, v in stats), url=f'{base()}/a/{a.id}',
                    thumb=(dist(a.distance, units).split(' ')[0] if a.distance else initials(a.title)),
                    thumb_bg=CLAY, vis=vis, chats=True, can_public=mine and a.visibility not in ('everyone',),
                    public=a.link_public, qr_label='', link=f'/activity/{a.id}',
                    story={'title': a.title, 'line': [[round(p[0], 5), round(p[1], 5)] for p in line],
                           'stats': [{'label': k, 'value': v} for k, v in stats]})
    if kind == 'segment':
        from apps.performance.models import Segment
        from apps.performance.segments import segment_page
        seg = get_object_or_404(Segment, pk=pk, is_active=True)
        p = segment_page(seg, viewer, 'club', request)
        pr = p['pr']
        rec = p['record']
        sub = ' · '.join(x for x in [f'Your PR {pr["time"]}' if pr else '',
                                     f'{rec["label"]} {rec["time"]}' if rec else ''] if x) or seg.area
        stats = [{'label': s['label'], 'value': f'{s["value"]} {s["unit"]}'.replace(' %', '%')} for s in p['stats'][:2]]
        if rec:
            stats.append({'label': rec['label'], 'value': rec['time']})
        return dict(kind=kind, id=seg.id, heading='Share this segment', title=seg.name, sub=sub,
                    url=f'{base()}/s/{seg.id}', thumb=pr['time'] if pr else initials(seg.name), thumb_bg=GOLD,
                    vis='Anyone with the link can see the segment', chats=True, can_public=False, public=False,
                    qr_label='', link=f'/segments/{seg.id}',
                    story={'title': seg.area or seg.name, 'line': p['line'], 'stats': stats,
                           'big': ({'label': f'Your PR · {seg.name}', 'value': pr['time'],
                                    'note': pr['note'].split(' · ')[-1].replace(' in club', ' in the club')}
                                   if pr else None)})
    if kind == 'route':
        from apps.routes.views import visible_routes
        r = visible_routes(viewer).filter(pk=pk).first()
        if not r:
            raise Http404
        vis = {'public': 'Anyone with the link can see the route', 'club': 'Only club members can open this link',
               'me': 'Only you can open this link'}[r.visibility]
        return dict(kind=kind, id=r.id, heading='Share this route', title=r.name,
                    sub=' · '.join(x for x in [dist(r.distance_m, units), climb(r.elevation_gain_m, units)] if x),
                    url=f'{base()}/r/{r.id}', thumb=dist(r.distance_m, units).split(' ')[0], thumb_bg=GOLD,
                    vis=vis, chats=True, can_public=False, public=False, qr_label='Scan to open the route',
                    story=None, link='/routes')
    raise Http404


def message_card(c):
    """What a Sent share looks like in a chat."""
    return {k: c[k] for k in ('kind', 'id', 'title', 'sub', 'url', 'thumb', 'thumb_bg', 'link')}


class ShareCardView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, kind, pk):
        return Response(card(kind, pk, request.user, request))

    def patch(self, request, kind, pk):
        if kind != 'activity':
            return _bad('kind', 'Only activities have a public link setting.')
        a = get_object_or_404(Activity, pk=pk, user=request.user)
        a.link_public = bool(request.data.get('public'))
        a.save(update_fields=['link_public'])
        return Response(card(kind, pk, request.user, request))


class RecipientsView(APIView):
    """People you message and follow; ride chats you're in (only for rides,
    routes and activities, so chats stay on topic)."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        from apps.chats.models import Chat
        from apps.chats.services import chat_title, other_in_direct
        from .models import Follow
        user = request.user
        hidden = blocked_ids(user)
        people, seen = [], set()
        for ch in (Chat.objects.filter(kind='direct', members__user=user).order_by('-last_message_at')[:8]):
            o = other_in_direct(ch, user)
            if o and o.is_active and o.id not in hidden and o.id not in seen:
                seen.add(o.id)
                people.append(dict(person(o, request), via='Direct'))
        for f in Follow.objects.filter(follower=user, followee__is_active=True).select_related('followee')[:30]:
            if len(people) >= 12:
                break
            if f.followee_id not in seen and f.followee_id not in hidden:
                seen.add(f.followee_id)
                people.append(dict(person(f.followee, request), via='You follow'))
        chats = []
        if request.query_params.get('kind') in ('event', 'activity', 'route', 'segment'):
            for ch in Chat.objects.filter(kind='ride', members__user=user, closes_at__gt=timezone.now()) \
                    .select_related('event').order_by('event__start_time')[:6]:
                chats.append({'id': ch.id, 'title': chat_title(ch, user), 'initials': initials(ch.event.title)})
        return Response({'people': people, 'chats': chats})


class SendView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    throttle_scope = 'messages'

    def get_throttles(self):
        from rest_framework.throttling import ScopedRateThrottle
        return [ScopedRateThrottle()]

    def post(self, request):
        from apps.chats.models import Chat, ChatMember
        from apps.chats.services import ChatClosed, SlowMode, direct_allowed, direct_chat, send
        d, user = request.data, request.user
        try:
            c = card(d.get('kind'), int(d.get('id')), user, request)
        except (TypeError, ValueError):
            return _bad('target', 'Missing what to share.')
        users = [int(x) for x in (d.get('users') or [])][:20]
        chat_ids = [int(x) for x in (d.get('chats') or [])][:10] if c['chats'] else []
        if not users and not chat_ids:
            return _bad('empty', 'Pick who to send to.')
        note = (d.get('note') or '').strip()[:500]
        sent = 0
        for other in User.objects.filter(id__in=users, is_active=True):
            if other.id == user.id or not direct_allowed(user, other):
                continue
            try:
                send(direct_chat(user, other), user, body=note, attachment='share', share=message_card(c))
                sent += 1
            except (SlowMode, ChatClosed, PermissionError):
                pass
        for ch in Chat.objects.filter(id__in=chat_ids, kind='ride'):
            if not ChatMember.objects.filter(chat=ch, user=user).exists():
                continue
            try:
                send(ch, user, body=note, attachment='share', share=message_card(c))
                sent += 1
            except (SlowMode, ChatClosed, PermissionError):
                pass
        if not sent:
            return _bad('not_sent', 'Couldn’t send that. Try again in a moment.')
        return Response({'sent': sent})


# ----------------------------------------------------------- public pages

def _svg_points(line, w=320, h=200, pad=14):
    """Fit [[lat, lng], ...] into an SVG viewbox."""
    if len(line) < 2:
        return ''
    lats, lngs = [p[0] for p in line], [p[1] for p in line]
    import math
    k = math.cos(math.radians(sum(lats) / len(lats)))
    xs = [x * k for x in lngs]
    span = max(max(xs) - min(xs), max(lats) - min(lats)) or 1e-6
    sx = (w - 2 * pad) / span
    ox = pad + ((w - 2 * pad) - (max(xs) - min(xs)) * sx) / 2
    oy = pad + ((h - 2 * pad) - (max(lats) - min(lats)) * sx) / 2
    return ' '.join(f'{ox + (x - min(xs)) * sx:.1f},{oy + (max(lats) - lat) * sx:.1f}' for x, lat in zip(xs, lats))


def _page(request, **ctx):
    ctx.setdefault('url', request.build_absolute_uri())
    return render(request, 'share/page.html', ctx)


def _not_shared(request, what):
    return _page(request, title='Shared with followers', eyebrow=what,
                 body='This is only visible to people the owner shares with on A Good Fit.', private=True,
                 status_code=200)


def public_profile(request, pk):
    u = get_object_or_404(User, pk=pk, is_active=True)
    p = person(u)
    from .models import Follow
    acts = Activity.objects.filter(user=u, visibility='everyone')
    return _page(request, eyebrow='On A Good Fit', title=p['name'], initials=p['initials'], photo=p['photo'],
                 subtitle=' · '.join(x for x in [u.neighborhood, u.headline] if x),
                 facts=[('Followers', f'{Follow.objects.filter(followee=u).count():,}'),
                        ('Public activities', f'{acts.count():,}')],
                 chips=[i.capitalize() for i in (u.interests or [])],
                 cta=f'Follow {p["first_name"]} in the A Good Fit app.')


def public_club(request, pk, inviter=None):
    c = get_object_or_404(Club, pk=pk)
    members = c.memberships.count()
    return _page(request, eyebrow=f'{inviter} invited you' if inviter else 'Club on A Good Fit', title=c.name,
                 initials=c.initials, color=c.color, subtitle=c.tagline or (c.location or c.neighborhood),
                 facts=[('Members', f'{members:,}')] + ([('Founded', str(c.founded_year))] if c.founded_year else []),
                 body=c.description if hasattr(c, 'description') else '',
                 cta=f'Join {c.name} in the A Good Fit app.')


def public_invite(request, code):
    hit = check_invite(code)
    if not hit:
        raise Http404
    inviter = User.objects.filter(pk=hit[1], is_active=True).first()
    return public_club(request, hit[0], inviter=person(inviter)['first_name'] if inviter else None)


def public_event(request, pk):
    e = get_object_or_404(Event, pk=pk, is_active=True)
    tz = safe_zone(e.host.timezone if e.host_id else 'UTC')
    going = e.rsvps.filter(status='going').count()
    facts = [('When', _when(e, tz)), ('Meet', e.location_name)]
    if e.distance_m:
        facts.append(('Distance', f'{dist(e.distance_m, "mi")} · {dist(e.distance_m, "km")}'))
    if e.pace:
        facts.append(('Pace', e.pace + (', no-drop' if e.no_drop else '')))
    facts.append(('Going', f'{going}'))
    line = e.route.line if e.route_id else []
    return _page(request, eyebrow='Cancelled' if e.is_cancelled else (e.club.name if e.club_id else 'Community ride'),
                 title=e.title, initials=initials(e.title), color=CLAY, facts=facts,
                 svg=_svg_points(sample(line, 200)) if line else '', cta='RSVP in the A Good Fit app.')


def public_activity(request, pk):
    a = get_object_or_404(Activity.objects.select_related('user'), pk=pk, user__is_active=True)
    if not (a.visibility == 'everyone' or a.link_public):
        return _not_shared(request, 'Activity')
    owner = person(a.user)
    facts = []
    if a.distance:
        facts.append(('Distance', f'{dist(a.distance, "mi")} · {dist(a.distance, "km")}'))
    facts.append(('Time', clock(a.moving_time or (a.duration or 0) * 60)))
    if a.distance and a.elevation_gain is not None:
        facts.append(('Elev Gain', f'{climb(a.elevation_gain, "mi")}'))
    line = sample(public_track(a.track_points(), a.user), 300) if getattr(a, 'is_gps', False) else []
    when = timezone.localtime(a.start_time, safe_zone(a.user.timezone))
    return _page(request, eyebrow=f'{owner["name"]} · {when:%b} {when.day}', title=a.title,
                 initials=owner['initials'], photo=owner['photo'], facts=facts,
                 svg=_svg_points(line) if len(line) > 1 else '', cta=f'See more from {owner["first_name"]} in the app.')


def public_route(request, pk):
    r = get_object_or_404(Route, pk=pk)
    if r.visibility != 'public':
        return _not_shared(request, 'Route')
    return _page(request, eyebrow='Route on A Good Fit', title=r.name, initials=initials(r.name), color=GOLD,
                 facts=[('Distance', f'{dist(r.distance_m, "mi")} · {dist(r.distance_m, "km")}'),
                        ('Elev Gain', climb(r.elevation_gain_m, 'mi')),
                        ('Type', 'Loop' if r.is_loop else 'Point to point')],
                 svg=_svg_points(sample(r.line, 300)), cta='Ride it with the A Good Fit app.')


def public_segment(request, pk):
    from apps.performance.models import Segment, SegmentEffort
    seg = get_object_or_404(Segment, pk=pk, is_active=True)
    best = (SegmentEffort.objects.filter(segment=seg, private=False, user__is_active=True)
            .select_related('user').order_by('elapsed_s').first())
    from apps.performance.segments import clock
    facts = [('Length', f'{dist(seg.distance_m, "mi")} · {dist(seg.distance_m, "km")}'),
             ('Avg Grade', f'{seg.avg_grade:.1f}%'),
             ('Attempts', f'{SegmentEffort.objects.filter(segment=seg).count():,}')]
    if best:
        facts.append(('Record', f'{clock(best.elapsed_s)} · {person(best.user)["first_name"]}'))
    return _page(request, eyebrow=f'Segment · {seg.area}' if seg.area else 'Segment', title=seg.name,
                 initials=initials(seg.name), color=GOLD, facts=facts, svg=_svg_points(seg.line),
                 cta='Ride it and see where you land in the A Good Fit app.')
