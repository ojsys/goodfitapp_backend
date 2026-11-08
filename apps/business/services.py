"""Business portal and featured events.

Who can act for an account: its BusinessMembers (the people who signed it up)
and, for accounts that run a club, the club's team through their club role
and the club's permission grid. Every portal request checks one permission.

Reporting is counts and percentages only. Breakdowns hide any group smaller
than MIN_GROUP (and say so) so no member can be singled out; a member's name
reaches a business only if they chose to share it at check-in.
"""

from collections import Counter
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from apps.events.models import Event, EventRSVP
from apps.social.models import ClubMembership, ClubTeamLog

from .models import (BusinessAccount, BusinessLog, BusinessMember, FeaturedImpression, FeaturedPlacement,
                     NameFlag, TeamInvite)

MIN_GROUP = getattr(settings, 'BUSINESS_MIN_GROUP', 10)
ROLE_ORDER = ['ride_leader', 'organizer', 'admin', 'owner']
INTEREST_LABELS = {
    'running': 'Running', 'cycling': 'Cycling', 'strength': 'Strength', 'yoga': 'Yoga', 'hiking': 'Hiking',
    'pilates': 'Pilates', 'hiit': 'HIIT', 'crossfit': 'CrossFit', 'walking': 'Walking', 'swimming': 'Swimming',
}
DEFAULT_NEIGHBORHOODS = ['Fort Greene', 'Clinton Hill', 'Prospect Heights', 'Boerum Hill', 'Park Slope',
                         'Williamsburg']


class Denied(Exception):
    def __init__(self, code, message, http=403, extra=None):
        super().__init__(message)
        self.code, self.message, self.http, self.extra = code, message, http, extra or {}


# ------------------------------------------------------------------ access

class Access:
    """What one person can do for one account."""

    def __init__(self, user, account):
        self.user, self.account = user, account
        bm = BusinessMember.objects.filter(account=account, user=user).first()
        self.club_member = None
        if account.club_id:
            self.club_member = ClubMembership.objects.filter(
                club_id=account.club_id, user=user, role__in=ClubMembership.TEAM_ROLES).first()
        roles = [r for r in (bm.role if bm else None, self.club_member.role if self.club_member else None) if r]
        self.role = max(roles, key=ROLE_ORDER.index) if roles else None
        if user.is_staff and self.role is None and account.is_house:
            self.role = 'owner'

    def can(self, perm):
        if self.role is None:
            return False
        if self.role == 'owner':
            return True
        if self.club_member and self.club_member.role == self.role:
            return self.club_member.can(perm)
        if self.account.club_id:
            grid = self.account.club.permissions.get(self.role) if self.account.club.permissions else None
            if grid is not None:
                return perm in grid
        return perm in ClubMembership.DEFAULT_PERMISSIONS.get(self.role, [])

    def need(self, perm):
        if not self.can(perm):
            raise Denied('forbidden', 'Your role doesn’t include this. Ask an owner or admin.')

    def perms(self):
        return {p: self.can(p) for p in ClubMembership.PERMISSIONS}


def accounts_for(user):
    ids = set(BusinessMember.objects.filter(user=user).values_list('account_id', flat=True))
    clubs = ClubMembership.objects.filter(user=user, role__in=('owner', 'admin', 'organizer')).values('club_id')
    ids |= set(BusinessAccount.objects.filter(club_id__in=clubs).values_list('id', flat=True))
    if user.is_staff:
        ids |= set(BusinessAccount.objects.filter(is_house=True).values_list('id', flat=True))
    return list(BusinessAccount.objects.filter(id__in=ids).select_related('club').order_by('is_house', 'name'))


def access(user, account_id):
    acct = BusinessAccount.objects.select_related('club').filter(pk=account_id).first()
    if acct is None:
        raise Denied('not_found', 'No such account.', 404)
    a = Access(user, acct)
    if a.role is None:
        raise Denied('forbidden', 'You aren’t on this account’s team.', 403)
    return a


def log(acct, actor, action):
    if acct.club_id:
        ClubTeamLog.objects.create(club_id=acct.club_id, actor=actor, action=action)
    else:
        BusinessLog.objects.create(account=acct, actor=actor, action=action)


def plan_line(acct):
    if acct.is_house:
        return 'Parent company · House account'
    bits = ['Verified' if acct.status == 'verified' else
            ('Not approved' if acct.status == 'rejected' else 'Verification pending')]
    if acct.partner:
        bits.append('Partner plan')
    return ' · '.join(bits)


def account_card(acct, user):
    a = Access(user, acct)
    return {'id': acct.id, 'name': acct.name, 'initials': acct.initials, 'is_house': acct.is_house,
            'verified': acct.verified, 'status': acct.status, 'line': plan_line(acct), 'role': a.role,
            'club': {'id': acct.club_id, 'name': acct.club.name} if acct.club_id else None,
            'partner': acct.partner, 'perms': a.perms()}


# ----------------------------------------------------------------- sign up

def check_signup(data):
    name = (data.get('name') or '').strip()
    if len(name) < 2:
        raise Denied('name', 'Add your business name.', 400)
    category = data.get('category') or 'other'
    if category not in dict(BusinessAccount.CATEGORIES):
        raise Denied('category', 'Pick a category.', 400)
    if not data.get('agree'):
        raise Denied('agree', 'Agree to the Community Guidelines and the Featured Events Policy to continue.', 400)
    return name, category


def signup(user, data):
    name, category = check_signup(data)
    with transaction.atomic():
        acct = BusinessAccount.objects.create(
            name=name[:120], category=category, address=(data.get('address') or '')[:200],
            website=(data.get('website') or '')[:200], work_email=data.get('email') or user.email,
            agreed_at=timezone.now())
        BusinessMember.objects.create(account=acct, user=user, role='owner')
        log(acct, user, 'created the business account')
    return acct


# ------------------------------------------------------------- targeting

def neighborhood_options():
    from apps.users.models import User
    rows = (User.objects.filter(is_active=True, guidelines_agreed_at__isnull=False).exclude(neighborhood='')
            .values('neighborhood').annotate(n=Count('id')).order_by('-n')[:24])
    names = [r['neighborhood'] for r in rows]
    for d in DEFAULT_NEIGHBORHOODS:
        if d not in names:
            names.append(d)
    return names


def audience(neighborhoods, interests):
    from apps.users.models import User
    q = User.objects.filter(is_active=True, guidelines_agreed_at__isnull=False)
    if neighborhoods:
        q = q.filter(neighborhood__in=neighborhoods)
    if interests:
        cond = Q()
        for i in interests:
            cond |= Q(interests__contains=[i])
        q = q.filter(cond)
    return q


def reach(neighborhoods, interests):
    n = audience(neighborhoods, interests).count()
    if n < MIN_GROUP:
        return {'count': None, 'label': f'Estimated reach: fewer than {MIN_GROUP} members a week'}
    rounded = round(n, -1) if n < 1000 else round(n, -2) if n < 10000 else round(n, -3)
    return {'count': rounded, 'label': f'Estimated reach: about {rounded:,} members a week'}


def matches(placement, user):
    if placement.neighborhoods and (user.neighborhood or '') not in placement.neighborhoods:
        return False
    if placement.interests and not set(placement.interests) & set(user.interests or []):
        return False
    return True


def why(placement, user):
    biz = placement.account.name
    if placement.account.is_house:
        return (f'{biz} runs A Good Fit and features its own events. Featured events never appear in your chats '
                'or A Good Match.')
    near = f' near {user.neighborhood}' if placement.neighborhoods and user.neighborhood else ''
    into = [INTEREST_LABELS.get(i, i).lower() for i in placement.interests if i in (user.interests or [])]
    into_s = f' who are into {" and ".join(into[:2])}' if placement.interests and into else ''
    shown = f'It’s shown to members{near}{into_s}.' if (near or into_s) else 'It’s shown to members in your area.'
    return f'{biz} paid to feature this event. {shown} Featured events never appear in your chats or A Good Match.'


# ------------------------------------------------- placements in the app

def live_placements(surface):
    now = timezone.now()
    return (FeaturedPlacement.objects.filter(status='approved', starts_at__lte=now, ends_at__gt=now,
                                             event__is_cancelled=False, event__start_time__gt=now)
            .select_related('account', 'event'))


def pick(user, surface, exclude_events=()):
    """The featured event for this member on Events / Home / the hub."""
    from apps.safety.visibility import blocked_ids
    blocked = blocked_ids(user)
    options = [p for p in live_placements(surface)
               if surface in p.spec['where'] and (p.package != 'partner' or p.account.partner or surface != 'hub')
               and p.event_id not in exclude_events and p.event.host_id not in blocked and matches(p, user)]
    if not options:
        return None
    # Rotate fairly: the one this member has seen least today.
    today = timezone.localdate()
    seen = dict(FeaturedImpression.objects.filter(user=user, day=today, placement__in=options)
                .values_list('placement_id', 'id'))
    options.sort(key=lambda p: (p.id in seen, p.starts_at))
    return options[0]


def featured_card(placement, user, request=None):
    from apps.social.home import event_card
    e, acct = placement.event, placement.account
    card = event_card(e, user, request)
    card.update({
        'kind': 'featured',
        'description': e.description,
        'duration_min': e.duration_min,
        'price_line': 'Free' if e.price_type == 'Free' else '',
        'featured': {
            'placement': placement.id, 'business': acct.name, 'initials': acct.initials,
            'verified': acct.verified,
            'host_line': f'Hosted by {acct.name}' + (' · Verified business' if acct.verified else ''),
            'why': why(placement, user),
        },
    })
    return card


def featured_for(user, surface, request=None, exclude_events=()):
    p = pick(user, surface, exclude_events)
    return featured_card(p, user, request) if p else None


def seen(user, placement_id, surface, tapped=False):
    p = FeaturedPlacement.objects.filter(pk=placement_id, status='approved').first()
    if p is None:
        return False
    row, _ = FeaturedImpression.objects.get_or_create(placement=p, user=user, day=timezone.localdate(),
                                                      defaults={'surface': surface[:8]})
    if tapped and not row.tapped:
        row.tapped = True
        row.save(update_fields=['tapped'])
    return True


# ------------------------------------------------------- featuring events

def _fmt_when(dt, tz):
    t = dt.astimezone(tz)
    return f'{t:%a %b} {t.day} · {t:%-I:%M %p}'


def placement_row(p, tz):
    stats = FeaturedImpression.objects.filter(placement=p).aggregate(v=Count('id'), t=Count('id', filter=Q(tapped=True)))
    rsvps = EventRSVP.objects.filter(event=p.event, status='going').count()
    checked = EventRSVP.objects.filter(event=p.event, checked_in=True).count()
    st = p.shown_status
    started = st in ('live', 'ended', 'scheduled')
    return {
        'id': p.id, 'title': p.event.title, 'when': _fmt_when(p.event.start_time, tz), 'status': st,
        'status_label': {'draft': 'Draft', 'in_review': 'In review', 'scheduled': 'Scheduled', 'live': 'Live',
                         'ended': 'Ended', 'rejected': 'Not approved', 'cancelled': 'Cancelled'}[st],
        'views': stats['v'] if started else None, 'rsvps': rsvps if started else None,
        'checked_in': checked, 'package': p.package, 'review_note': p.review_note,
    }


def draft_payload(p, tz):
    e = p.event
    t = e.start_time.astimezone(tz)
    return {'id': p.id, 'status': p.status, 'title': e.title, 'date': t.date().isoformat(), 'time': f'{t:%H:%M}',
            'location': e.location_name, 'description': e.description, 'package': p.package,
            'neighborhoods': p.neighborhoods, 'interests': p.interests, 'review_note': p.review_note}


def save_draft(a, data, placement=None):
    """Create or update a draft (or an event sent back after review)."""
    from datetime import datetime
    from apps.users.age_gate import safe_zone
    a.need('feature_events')
    acct, user = a.account, a.user
    title = (data.get('title') or '').strip()
    if len(title) < 3:
        raise Denied('title', 'Add an event name.', 400)
    try:
        tz = safe_zone(data.get('timezone') or user.timezone or 'America/New_York')
        start = datetime.fromisoformat(f'{data.get("date")}T{data.get("time") or "09:00"}').replace(tzinfo=tz)
    except (TypeError, ValueError):
        raise Denied('date', 'Pick a date and start time.', 400)
    if start <= timezone.now() + timedelta(hours=12):
        raise Denied('date', 'Pick a date at least a day away so there’s time to review it.', 400)
    location = (data.get('location') or '').strip()
    if not location:
        raise Denied('location', 'Add where it happens.', 400)
    package = data.get('package') or 'spotlight'
    if package not in FeaturedPlacement.PACKAGES:
        raise Denied('package', 'Pick a package.', 400)
    hoods = [h for h in (data.get('neighborhoods') or []) if isinstance(h, str)][:12]
    interests = [i for i in (data.get('interests') or []) if i in INTEREST_LABELS][:6]
    activity = next((i for i in interests if i in ('cycling', 'running', 'walking', 'hiking')), None)
    fields = dict(
        title=title[:200], description=(data.get('description') or '')[:2000], start_time=start,
        location_name=location[:200], location_address=location[:500],
        activity_type={'cycling': 'ride', 'running': 'run', 'walking': 'walk', 'hiking': 'hike'}.get(activity, 'class'),
        host_name=acct.name, host_label=f'Hosted by {acct.name}' + (' · Verified business' if acct.verified else ''),
        tags=interests, club=acct.club,
    )
    with transaction.atomic():
        if placement is None:
            e = Event.objects.create(host=user, vibe='Social', kind='featured', is_active=False,
                                     who_can_join='anyone', **fields)
            placement = FeaturedPlacement.objects.create(account=acct, event=e, created_by=user)
        else:
            if placement.status not in ('draft', 'rejected', 'in_review'):
                raise Denied('locked', 'This event is already approved. Contact us to change it.', 409)
            for k, v in fields.items():
                setattr(placement.event, k, v)
            placement.event.save()
            if placement.status == 'rejected':
                placement.status = 'draft'
        placement.package, placement.neighborhoods, placement.interests = package, hoods, interests
        placement.price_cents = FeaturedPlacement.PACKAGES[package]['price']
        placement.save()
    return placement


def partner_used(acct, now=None):
    now = now or timezone.now()
    first = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return FeaturedPlacement.objects.filter(account=acct, package='partner', submitted_at__gte=first,
                                            status__in=('in_review', 'approved')).count()


def submit(a, placement):
    from . import billing
    a.need('feature_events')
    acct = a.account
    if placement.status not in ('draft', 'rejected'):
        raise Denied('submitted', 'This event was already sent for review.', 409)
    if not acct.verified:
        raise Denied('unverified', 'We’re still verifying your business (usually within 1 business day). '
                     'Your draft is saved.', 409)
    if placement.package == 'partner':
        if not acct.partner:
            raise Denied('partner_required', 'The Partner package needs the Partner plan.', 402)
        if not acct.is_house and partner_used(acct) >= FeaturedPlacement.PARTNER_EVENTS_A_MONTH:
            raise Denied('partner_limit', 'You’ve used all 4 Partner events this month. Pick Spotlight or Boost.', 409)
    elif not acct.is_house and billing.configured() and not acct.stripe_payment_method:
        raise Denied('card_required', 'Add a card first. You’re only charged once the event is approved.', 402)
    placement.status, placement.submitted_at, placement.review_note = 'in_review', timezone.now(), ''
    placement.save()
    log(acct, a.user, f'submitted {placement.event.title} for review')
    return placement


def approve(placement, reviewer):
    """A person at A Good Fit reviewed it: charge, then schedule it."""
    from . import billing
    if placement.status != 'in_review':
        raise Denied('state', 'Only events in review can be approved.', 409)
    acct = placement.account
    if acct.is_house:
        placement.payment = 'house'
    elif placement.package == 'partner' and acct.partner:
        placement.payment = 'included'
    elif not billing.configured():
        placement.payment = 'not_billed'
    else:
        ok, ref = billing.charge(acct, placement.price_cents, f'Featured: {placement.event.title}',
                                 f'placement-{placement.id}')
        placement.stripe_payment_intent = ref or ''
        if not ok:
            placement.payment = 'failed'
            placement.save()
            raise Denied('charge_failed', 'The card was declined. The business needs to update its card.', 402)
        placement.payment = 'charged'
    e = placement.event
    now = timezone.now()
    placement.starts_at = max(now, e.start_time - timedelta(days=placement.spec['days']))
    placement.ends_at = e.start_time
    placement.status, placement.reviewed_at, placement.reviewed_by = 'approved', now, reviewer
    placement.save()
    e.is_active = True
    e.host_label = f'Hosted by {acct.name}' + (' · Verified business' if acct.verified else '')
    e.save(update_fields=['is_active', 'host_label'])
    log(acct, reviewer, f'approved {e.title} ({placement.spec["name"]})')
    _email(acct, f'{e.title} is approved',
           f'Your featured event {e.title} is approved and goes live {placement.starts_at:%b %-d}.')
    return placement


def reject(placement, reviewer, note):
    if placement.status != 'in_review':
        raise Denied('state', 'Only events in review can be sent back.', 409)
    placement.status, placement.review_note = 'rejected', (note or 'It doesn’t fit the Featured Events Policy.')[:300]
    placement.reviewed_at, placement.reviewed_by = timezone.now(), reviewer
    placement.save()
    _email(placement.account, f'{placement.event.title} needs changes',
           f'We couldn’t approve {placement.event.title}: {placement.review_note} You can edit it and send it again.')


def _email(acct, subject, body):
    if not acct.work_email:
        return
    from django.core.mail import send_mail
    send_mail(subject, body, None, [acct.work_email], fail_silently=True)


# ----------------------------------------------------------------- numbers

def _window(acct, start, end):
    imp = FeaturedImpression.objects.filter(placement__account=acct, day__gte=start.date(), day__lt=end.date())
    events = FeaturedPlacement.objects.filter(account=acct).values('event_id')
    rs = EventRSVP.objects.filter(event_id__in=events)
    return {
        'views': imp.count(), 'taps': imp.filter(tapped=True).count(),
        'rsvps': rs.filter(status='going', created_at__gte=start, created_at__lt=end).count(),
        'checkins': rs.filter(checked_in=True, check_in_time__gte=start, check_in_time__lt=end).count(),
    }


def _change(now, before):
    if not before:
        return None
    return round(100 * (now - before) / before)


def overview(a):
    from apps.users.age_gate import safe_zone
    a.need('see_event_data')
    acct, tz = a.account, safe_zone(a.user.timezone or 'America/New_York')
    now = timezone.now()
    cur = _window(acct, now - timedelta(days=30), now + timedelta(days=1))
    prev = _window(acct, now - timedelta(days=60), now - timedelta(days=30))
    showed = round(100 * cur['checkins'] / cur['rsvps']) if cur['rsvps'] else None
    stats = [
        {'label': 'Views', 'value': cur['views'], 'change': _change(cur['views'], prev['views'])},
        {'label': 'Taps', 'value': cur['taps'], 'change': _change(cur['taps'], prev['taps'])},
        {'label': 'RSVPs', 'value': cur['rsvps'], 'change': _change(cur['rsvps'], prev['rsvps'])},
        {'label': 'Check-ins', 'value': cur['checkins'],
         'note': f'{showed}% of RSVPs showed up' if showed is not None else 'Counted at your events'},
    ]
    # RSVPs by week (Mondays), last 6 weeks.
    today = timezone.localtime(now, tz).date()
    monday = today - timedelta(days=today.weekday())
    weeks = []
    events = FeaturedPlacement.objects.filter(account=acct).values('event_id')
    for k in range(5, -1, -1):
        w0 = monday - timedelta(weeks=k)
        n = EventRSVP.objects.filter(event_id__in=events, status='going', created_at__date__gte=w0,
                                     created_at__date__lt=w0 + timedelta(days=7)).count()
        weeks.append({'label': f'{w0:%b} {w0.day}', 'value': n})
    rows = [placement_row(p, tz) for p in
            FeaturedPlacement.objects.filter(account=acct).exclude(status='cancelled').select_related('event')
            .order_by('-event__start_time')[:20]]
    plan = None
    if acct.is_house:
        plan = {'name': 'House account', 'status': 'Active', 'line': 'Featured events are free for GoodCo.'}
    elif acct.partner:
        used = partner_used(acct)
        renews = f' Renews {acct.plan_renews_at.astimezone(tz):%b} {acct.plan_renews_at.astimezone(tz).day}.' \
            if acct.plan_renews_at else ''
        plan = {'name': 'Partner plan', 'status': 'Active' if acct.plan_status == 'active' else 'Payment failed',
                'line': f'{used} of {FeaturedPlacement.PARTNER_EVENTS_A_MONTH} featured events used this month.{renews}',
                'used': used, 'of': FeaturedPlacement.PARTNER_EVENTS_A_MONTH}
    return {'stats': stats, 'events': rows, 'weeks': weeks, 'plan': plan}


def _breakdown(values, other_label='Other'):
    """Percent per group; groups under MIN_GROUP fold into Other."""
    total = len(values)
    if total < MIN_GROUP:
        return None
    c = Counter(values)
    rows, other = [], 0
    for k, n in c.most_common():
        if k and n >= MIN_GROUP and len(rows) < 4:
            rows.append([k, n])
        else:
            other += n
    if other:
        rows.append([other_label, other])
    return [{'label': k, 'pct': round(100 * n / total)} for k, n in rows]


def results(a, placement):
    from apps.users.age_gate import safe_zone
    a.need('see_event_data')
    tz = safe_zone(a.user.timezone or 'America/New_York')
    p, e = placement, placement.event
    imp = FeaturedImpression.objects.filter(placement=p)
    views, taps = imp.count(), imp.filter(tapped=True).count()
    going = list(EventRSVP.objects.filter(event=e, status='going').select_related('user'))
    checked = [r for r in going if r.checked_in]
    today = timezone.localdate()
    per_day = []
    if p.starts_at:
        d = timezone.localtime(p.starts_at).date()
        end = min(today, timezone.localtime(p.ends_at).date()) if p.ends_at else today
        counts = dict(imp.values('day').annotate(n=Count('id')).values_list('day', 'n'))
        while d <= end and len(per_day) < 31:
            per_day.append({'label': f'{d:%b} {d.day}', 'value': counts.get(d, 0)})
            d += timedelta(days=1)
    acct = p.account
    if p.payment == 'house':
        cost, cost_note = None, 'Free on the house account'
    elif p.package == 'partner':
        per_event = p.price_cents / FeaturedPlacement.PARTNER_EVENTS_A_MONTH
        cost = f'${per_event / 100 / len(going):.2f}' if going else None
        cost_note = f'About ${per_event / 100:.0f} per event on Partner'
    else:
        cost = f'${p.price_cents / 100 / len(going):.2f}' if going else None
        cost_note = f'{p.spec["name"]} · ${p.price_cents / 100:.0f}'
    st = p.shown_status
    runs = (f'Featured on {"the Partner plan" if p.package == "partner" else p.spec["name"]}, '
            f'{timezone.localtime(p.starts_at, tz):%b %-d} to {timezone.localtime(p.ends_at, tz):%b %-d}'
            if p.starts_at else '')
    pct = lambda a_, b_: f'{round(100 * a_ / b_)}%' if b_ else '–'  # noqa: E731
    return {
        'id': p.id, 'title': e.title, 'status': st,
        'status_label': placement_row(p, tz)['status_label'],
        'line': ' · '.join(x for x in [_fmt_when(e.start_time, tz), e.location_name, runs] if x),
        'stats': [
            {'label': 'Views', 'value': views, 'note': f'{imp.filter(day=today).count():,} today'},
            {'label': 'Taps', 'value': taps, 'note': f'{pct(taps, views)} of views'},
            {'label': 'RSVPs', 'value': len(going), 'note': f'{pct(len(going), taps)} of taps'},
            {'label': 'Cost per RSVP', 'value': cost or '–', 'note': cost_note},
        ],
        'per_day': per_day,
        'funnel': [{'label': 'Views', 'value': views}, {'label': 'Taps', 'value': taps},
                   {'label': 'RSVPs', 'value': len(going)}, {'label': 'Check-ins', 'value': len(checked)}],
        'checkin_note': (f'Counted at the event on {timezone.localtime(e.start_time, tz):%a %b} '
                         f'{timezone.localtime(e.start_time, tz).day}'),
        'neighborhoods': _breakdown([r.user.neighborhood or '' for r in going]),
        'interests': _breakdown([INTEREST_LABELS.get((r.user.interests or [''])[0], '') for r in going]),
        'min_group': MIN_GROUP,
        'shared_names': [r.user.first_name or r.user.full_name for r in checked if getattr(r, 'share_name', False)],
        'editable': p.status in ('draft', 'rejected'),
    }


# -------------------------------------------------------- suggested rides

def _suggester_line(s, club):
    m = ClubMembership.objects.filter(club=club, user=s.member).first()
    if m and m.role in ClubMembership.TEAM_ROLES:
        return f'{m.role_label} for {club.name.split()[0]}'
    hosted = Event.objects.filter(host=s.member, kind='community', start_time__lt=timezone.now(), is_cancelled=False)
    n = hosted.count()
    if n:
        riders = EventRSVP.objects.filter(event__in=hosted, status='going').exclude(user=s.member).count()
        return f'Has hosted {n} community ride{"s" if n != 1 else ""} · {riders} rider{"s" if riders != 1 else ""} total'
    earlier = club.suggestions.filter(member=s.member, created_at__lt=s.created_at).count()
    return 'First ride they’ve suggested' if not earlier else f'Has suggested {earlier + 1} rides'


def suggestion_card(s, tz):
    from datetime import datetime
    from apps.social import community
    from apps.routes.models import Route
    p = s.proposal
    try:
        start = datetime.fromisoformat(p['start']).astimezone(tz)
        when = f'{start:%a %b} {start.day} · {start:%-I:%M %p}'
    except (KeyError, ValueError, TypeError):
        when = ''
    route = Route.objects.filter(pk=p.get('route')).first() if p.get('route') else None
    route_bit = f'{route.name} · {route.distance_m / 1609.344:.1f} mi' if route else 'No set route'
    pace = community.PACE_LABELS.get(p.get('pace'), '') if hasattr(community, 'PACE_LABELS') else ''
    u = s.member
    return {
        'id': s.id, 'status': s.status, 'title': p.get('title', ''),
        'line': ' · '.join(x for x in [when, p.get('meeting_spot', '')] if x),
        'line2': ' · '.join(x for x in [route_bit, f'{pace.capitalize()}{", no-drop" if p.get("no_drop") else ""}'] if x),
        'note': s.note,
        'member': {'id': u.id, 'name': u.full_name or u.first_name, 'first_name': u.first_name,
                   'initials': ''.join(w[0] for w in (u.full_name or u.first_name or '?').split()[:2]).upper(),
                   'line': _suggester_line(s, s.club)},
    }


def suggestions(a):
    from apps.social.models import RideSuggestion
    from apps.users.age_gate import safe_zone
    a.need('approve_suggestions')
    club = a.account.club
    if club is None:
        raise Denied('no_club', 'Suggested rides are for accounts that run a club.', 404)
    tz = safe_zone(a.user.timezone or 'America/New_York')
    qs = RideSuggestion.objects.filter(club=club, status='new').select_related('member')
    return {'club': club.name, 'is_house': a.account.is_house,
            'suggestions': [suggestion_card(s, tz) for s in qs.order_by('created_at')],
            'flags': name_flags(club, tz)}


def decide_suggestion(a, sid, action):
    from apps.notifications.services import B, T, notify
    from apps.social.community_views import approve_suggestion
    from apps.social.models import RideSuggestion
    a.need('approve_suggestions')
    s = RideSuggestion.objects.filter(pk=sid, club=a.account.club).select_related('club', 'member').first()
    if s is None:
        raise Denied('not_found', 'That suggestion is gone.', 404)
    club = s.club
    if action == 'approve':
        if s.status != 'new':
            raise Denied('state', 'Already decided.', 409)
        e = approve_suggestion(s, a.user, checked=True)
        notify(s.member, 'ride_update', [B(club.name), T(' approved '), B(e.title),
                                         T('. It’s on the club calendar and you’re the ride leader.')],
               link=f'/events/{e.id}')
    elif action == 'decline':
        if s.status != 'new':
            raise Denied('state', 'Already decided.', 409)
        s.status, s.reviewed_by = 'declined', a.user
        s.save()
        ClubTeamLog.objects.create(club=club, actor=a.user, action=f'declined {s.member.first_name}’s suggested ride, '
                                                                  f'{s.proposal.get("title", "")}')
        notify(s.member, 'ride_update', [B(club.name), T(' couldn’t add '), B(s.proposal.get('title', 'your ride')),
                                         T(' as a club ride this time. Thanks for suggesting it. You can still host it '
                                           'as a community ride.')], link='/events/host')
    elif action == 'undo':
        if s.status == 'approved' and s.event_id:
            e = s.event
            others = EventRSVP.objects.filter(event=e, status='going').exclude(user=s.member).exists()
            if others:
                raise Denied('has_rsvps', 'People already RSVP’d to this ride. Cancel it from the club instead.', 409)
            s.event = None
            s.save(update_fields=['event'])
            e.delete()
        s.status, s.reviewed_by = 'new', None
        s.save()
        ClubTeamLog.objects.create(club=club, actor=a.user, action=f'undid the decision on {s.proposal.get("title", "")}')
    else:
        raise Denied('action', 'Unknown action.', 400)
    from apps.users.age_gate import safe_zone
    return suggestion_card(s, safe_zone(a.user.timezone or 'America/New_York'))


def message_member(a, sid):
    from apps.chats.services import direct_allowed, direct_chat
    from apps.social.models import RideSuggestion
    a.need('approve_suggestions')
    s = RideSuggestion.objects.filter(pk=sid, club=a.account.club).first()
    if s is None:
        raise Denied('not_found', 'That suggestion is gone.', 404)
    if not a.user.guidelines_agreed_at:
        raise Denied('not_member', 'Messages are sent from the A Good Fit app. Sign in to the app as a team member.', 409)
    if not direct_allowed(a.user, s.member):
        raise Denied('not_allowed', 'You can’t message this member.', 403)
    chat = direct_chat(a.user, s.member)
    return {'chat': chat.id, 'message': f'Chat with {s.member.first_name} is open in your A Good Fit app.'}


def _brand_word(club):
    words = [w for w in club.name.split() if len(w) >= 4 and w.lower() not in ('club', 'bike', 'run', 'running',
                                                                              'yoga', 'the')]
    return words[0] if words else club.name


def name_flags(club, tz):
    word = _brand_word(club)
    team = ClubMembership.objects.filter(club=club, role__in=ClubMembership.TEAM_ROLES).values('user_id')
    hits = Event.objects.filter(kind='community', is_cancelled=False, start_time__gte=timezone.now(),
                                title__icontains=word).exclude(host_id__in=team)
    for e in hits:
        NameFlag.objects.get_or_create(club=club, event=e)
    out = []
    for f in NameFlag.objects.filter(club=club, status='open', event__start_time__gte=timezone.now(),
                                     event__is_cancelled=False).select_related('event', 'event__host'):
        h = f.event.host
        out.append({'id': f.id, 'title': f.event.title,
                    'line': f'Community ride by {h.first_name} {h.last_name[:1] + "." if h.last_name else ""} · '
                            f'{_fmt_when(f.event.start_time, tz)}'.replace('  ', ' ')})
    return out


def decide_flag(a, fid, action):
    from apps.notifications.services import B, T, notify
    a.need('approve_suggestions')
    f = NameFlag.objects.filter(pk=fid, club=a.account.club).select_related('event', 'event__host', 'club').first()
    if f is None:
        raise Denied('not_found', 'Not found.', 404)
    if action == 'rename':
        f.status = 'asked'
        notify(f.event.host, 'ride_update', [B(f.club.name), T(' asked you to rename '), B(f.event.title),
                                             T(' so members don’t think the club runs it. Thanks!')],
               link=f'/events/{f.event_id}')
        msg = f'Asked {f.event.host.first_name} to rename it.'
    elif action == 'allow':
        f.status = 'allowed'
        msg = 'Okay. We won’t flag this ride again.'
    else:
        raise Denied('action', 'Unknown action.', 400)
    f.decided_by, f.decided_at = a.user, timezone.now()
    f.save()
    ClubTeamLog.objects.create(club=f.club, actor=a.user,
                               action=f'{"asked to rename" if action == "rename" else "allowed"} {f.event.title}')
    return {'id': f.id, 'message': msg}


# ------------------------------------------------------------------- team

PERM_ROWS = [
    ('create_events', 'Create rides and events'), ('approve_suggestions', 'Approve member suggestions'),
    ('run_rides', 'Run assigned rides'), ('post_announcements', 'Post announcements'),
    ('moderate', 'Moderate chats and review reports'), ('edit_club', 'Edit the club page'),
    ('feature_events', 'Feature events'), ('see_event_data', 'See event data'),
    ('manage_team', 'Manage the team'), ('manage_billing', 'Manage billing'),
]
EDITABLE_ROLES = ['admin', 'organizer', 'ride_leader']


def _initials(u):
    return ''.join(w[0] for w in (u.full_name or u.first_name or u.email).split()[:2]).upper()


def grid(club):
    out = {}
    for r in EDITABLE_ROLES:
        g = club.permissions.get(r) if club.permissions else None
        out[r] = list(g if g is not None else ClubMembership.DEFAULT_PERMISSIONS[r])
    return out


def team(a):
    from apps.users.age_gate import safe_zone
    acct = a.account
    tz = safe_zone(a.user.timezone or 'America/New_York')
    if not acct.club_id:
        people = [{'id': m.user_id, 'name': m.user.full_name or m.user.email, 'initials': _initials(m.user),
                   'line': 'Business account', 'role': m.role, 'pending': False}
                  for m in acct.members.select_related('user')]
        logs = [{'who': l.actor.first_name if l.actor else 'Someone', 'initials': _initials(l.actor) if l.actor else '?',
                 'what': l.action, 'when': _when_short(l.created_at, tz)} for l in acct.log.select_related('actor')[:20]]
        return {'club': None, 'people': people, 'grid': None, 'rows': PERM_ROWS, 'log': logs,
                'can_manage': a.can('manage_team')}
    club = acct.club
    people = []
    for m in ClubMembership.objects.filter(club=club, role__in=ClubMembership.TEAM_ROLES).select_related('user') \
            .order_by('joined_at'):
        people.append({'id': m.user_id, 'name': m.user.full_name or m.user.first_name, 'initials': _initials(m.user),
                       'line': m.title or f'Joined {m.joined_at.astimezone(tz):%b %Y}', 'role': m.role,
                       'pending': False})
    for inv in TeamInvite.objects.filter(club=club, status='pending').select_related('user'):
        people.append({'id': inv.user_id, 'invite': inv.id, 'name': inv.user.full_name or inv.user.first_name,
                       'initials': _initials(inv.user), 'line': f'Invite pending · Invited {inv.created_at.astimezone(tz):%b} '
                       f'{inv.created_at.astimezone(tz).day}', 'role': inv.role, 'pending': True})
    logs = [{'who': l.actor.first_name if l.actor else 'Someone', 'initials': _initials(l.actor) if l.actor else '?',
             'what': l.action, 'when': _when_short(l.created_at, tz)}
            for l in ClubTeamLog.objects.filter(club=club).select_related('actor')[:20]]
    return {'club': club.name, 'people': people, 'grid': grid(club), 'rows': PERM_ROWS, 'log': logs,
            'can_manage': a.can('manage_team'), 'me': a.user.id}


def _when_short(dt, tz):
    t = dt.astimezone(tz)
    if timezone.now() - dt < timedelta(days=6):
        return f'{t:%a %-I:%M %p}'
    return f'{t:%b} {t.day}'


def search_members(a, q):
    from apps.safety.visibility import blocked_ids
    from apps.users.models import User
    a.need('manage_team')
    q = (q or '').strip()
    if len(q) < 2 or not a.account.club_id:
        return []
    on_team = ClubMembership.objects.filter(club_id=a.account.club_id, role__in=ClubMembership.TEAM_ROLES) \
        .values('user_id')
    parts = q.split()
    cond = Q(first_name__istartswith=parts[0]) | Q(last_name__istartswith=parts[0])
    if len(parts) > 1:
        cond = Q(first_name__istartswith=parts[0], last_name__istartswith=parts[-1])
    users = (User.objects.filter(cond, is_active=True, guidelines_agreed_at__isnull=False)
             .exclude(id__in=on_team).exclude(id__in=blocked_ids(a.user))[:8])
    return [{'id': u.id, 'name': u.full_name or u.first_name, 'initials': _initials(u),
             'line': u.neighborhood or ''} for u in users]


def invite(a, user_id, role):
    from apps.notifications.services import B, T, notify
    from apps.users.models import User
    a.need('manage_team')
    club = a.account.club
    if club is None:
        raise Denied('no_club', 'Teams are for accounts that run a club.', 404)
    if role not in EDITABLE_ROLES:
        raise Denied('role', 'Pick a role.', 400)
    u = User.objects.filter(pk=user_id, is_active=True, guidelines_agreed_at__isnull=False).first()
    if u is None:
        raise Denied('not_found', 'Couldn’t find that member.', 404)
    if ClubMembership.objects.filter(club=club, user=u, role__in=ClubMembership.TEAM_ROLES).exists():
        raise Denied('on_team', f'{u.first_name} is already on the team.', 409)
    inv, created = TeamInvite.objects.get_or_create(club=club, user=u, status='pending',
                                                    defaults={'role': role, 'invited_by': a.user})
    if not created:
        inv.role = role
        inv.save(update_fields=['role'])
    label = dict(ClubMembership.ROLES)[role].lower()
    notify(u, 'team_invite', [B(a.user.first_name or club.name), T(' invited you to join the '), B(club.name),
                              T(f' team as {"an" if label[0] in "aeiou" else "a"} {label}.')],
           actor=a.user if a.user.guidelines_agreed_at else None, link=f'/clubs/{club.id}',
           group_key=f'team_invite:{inv.id}')
    ClubTeamLog.objects.create(club=club, actor=a.user, action=f'invited {u.full_name} as a {label}')
    return inv


def set_role(a, user_id, role):
    a.need('manage_team')
    club = a.account.club
    if role not in EDITABLE_ROLES:
        raise Denied('role', 'Pick a role.', 400)
    inv = TeamInvite.objects.filter(club=club, user_id=user_id, status='pending').first()
    if inv:
        inv.role = role
        inv.save(update_fields=['role'])
        return
    m = ClubMembership.objects.filter(club=club, user_id=user_id, role__in=ClubMembership.TEAM_ROLES).first()
    if m is None:
        raise Denied('not_found', 'Not on the team.', 404)
    if m.role == 'owner':
        raise Denied('owner', 'Owners keep every permission.', 409)
    if m.user_id == a.user.id:
        raise Denied('self', 'Ask another owner or admin to change your role.', 409)
    m.role = role
    m.save(update_fields=['role'])
    ClubTeamLog.objects.create(club=club, actor=a.user,
                               action=f'made {m.user.full_name} {dict(ClubMembership.ROLES)[role].lower()}')


def remove(a, user_id):
    a.need('manage_team')
    club = a.account.club
    inv = TeamInvite.objects.filter(club=club, user_id=user_id, status='pending').first()
    if inv:
        inv.status = 'cancelled'
        inv.save(update_fields=['status'])
        ClubTeamLog.objects.create(club=club, actor=a.user, action=f'cancelled the invite to {inv.user.full_name}')
        return
    m = ClubMembership.objects.filter(club=club, user_id=user_id, role__in=ClubMembership.TEAM_ROLES).first()
    if m is None:
        raise Denied('not_found', 'Not on the team.', 404)
    if m.role == 'owner':
        raise Denied('owner', 'Owners can’t be removed here. Contact us.', 409)
    if m.user_id == a.user.id:
        raise Denied('self', 'Ask another owner or admin to remove you.', 409)
    m.role = 'member'  # stays in the club as a member
    m.save(update_fields=['role'])
    ClubTeamLog.objects.create(club=club, actor=a.user, action=f'removed {m.user.full_name} from the team')


def set_grid(a, role, perm, on):
    a.need('manage_team')
    club = a.account.club
    if role not in EDITABLE_ROLES or perm not in ClubMembership.PERMISSIONS:
        raise Denied('grid', 'Unknown permission.', 400)
    if perm == 'manage_billing':
        raise Denied('billing', 'Only owners manage billing.', 409)
    g = grid(club)
    cur = set(g[role])
    (cur.add if on else cur.discard)(perm)
    g[role] = [p for p in ClubMembership.PERMISSIONS if p in cur]
    club.permissions = g
    club.save(update_fields=['permissions'])
    label = dict(PERM_ROWS)[perm].lower()
    ClubTeamLog.objects.create(club=club, actor=a.user, action=f'{"let" if on else "stopped"} '
                               f'{dict(ClubMembership.ROLES)[role].lower()}s {label}')
    return g


def answer_invite(user, invite_id, accept):
    inv = TeamInvite.objects.filter(pk=invite_id, user=user, status='pending').select_related('club').first()
    if inv is None:
        raise Denied('not_found', 'That invite isn’t open anymore.', 404)
    inv.status, inv.answered_at = ('accepted' if accept else 'declined'), timezone.now()
    inv.save()
    if accept:
        m, _ = ClubMembership.objects.get_or_create(club=inv.club, user=user, defaults={'role': inv.role})
        if m.role not in ('owner', 'admin') or ROLE_ORDER.index(inv.role) > ROLE_ORDER.index(m.role):
            m.role = inv.role
            m.save(update_fields=['role'])
        ClubTeamLog.objects.create(club=inv.club, actor=user,
                                   action=f'joined the team as {dict(ClubMembership.ROLES)[inv.role].lower()}')
    return inv


def pending_invite(user, club):
    inv = TeamInvite.objects.filter(user=user, club=club, status='pending').first()
    if inv is None:
        return None
    return {'id': inv.id, 'role': inv.role, 'role_label': dict(ClubMembership.ROLES)[inv.role],
            'from': inv.invited_by.first_name if inv.invited_by else club.name}
