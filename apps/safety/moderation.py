"""
Moderation outcomes. Each one resolves every open report about the same
thing, records what was done, and sets the line the reporter sees in Your
reports.
"""

from django.db import transaction
from django.utils import timezone

from .models import ModerationAction, Report

NOUN = {'message': 'message', 'post': 'post', 'comment': 'comment', 'activity': 'activity', 'member': 'profile'}

NOTES = {
    'no_violation': 'We reviewed it and it didn’t break our guidelines. You can still block anyone, anytime.',
    'remove_warn': 'We removed the {noun} and the member got a warning. Repeat issues lead to removal.',
    'warn': 'We talked to the member and they got a warning. Repeat issues lead to removal.',
    'suspend': 'We removed the {noun} and suspended the member while we look into it further.',
    'age_check': 'We paused the account until the member confirms they’re 21 or older. Thanks for flagging it.',
    'ban': 'We removed the member from A Good Fit. Thanks for looking out.',
}


def _same_target(report):
    return Report.objects.filter(target_kind=report.target_kind, target_id=report.target_id, status='open')


def remove_content(report, moderator):
    """Take the reported thing down. Returns True if something was removed."""
    kind, pk = report.target_kind, report.target_id
    if kind == 'message':
        from apps.chats.models import ChatMessage
        return bool(ChatMessage.objects.filter(pk=pk, removed_at__isnull=True)
                    .update(removed_by=moderator, removed_at=timezone.now()))
    if kind == 'post':
        from apps.social.models import Post
        return bool(Post.objects.filter(pk=pk).delete()[0])
    if kind == 'comment':
        from apps.social.models import Comment
        return bool(Comment.objects.filter(pk=pk).delete()[0])
    if kind == 'activity':
        from apps.activities.models import Activity
        # Kept for its owner, hidden from everyone else.
        return bool(Activity.objects.filter(pk=pk).update(visibility='me'))
    return False


def _deactivate(user):
    if user and user.is_active:
        user.is_active = False
        user.save(update_fields=['is_active'])


@transaction.atomic
def decide(report, decision, moderator, note=''):
    """decision: no_violation | remove_warn | warn | suspend | age_check | ban"""
    member = report.target_user
    noun = NOUN.get(report.target_kind, 'content')
    text = note or NOTES[decision].format(noun=noun)
    outcome = 'no_violation' if decision == 'no_violation' else 'action_taken'
    reports = list(_same_target(report))
    if decision in ('suspend', 'age_check', 'ban') and member:
        # A decision about the person settles every open report about them.
        reports += list(Report.objects.filter(target_user=member, status='open').exclude(
            id__in=[r.id for r in reports]))

    if decision in ('remove_warn', 'suspend') and report.target_kind != 'member':
        if remove_content(report, moderator) and member:
            ModerationAction.objects.create(member=member, kind='removed_content', report=report, by=moderator,
                                            note=f'{noun} #{report.target_id}')
    if member and decision in ('remove_warn', 'warn'):
        ModerationAction.objects.create(member=member, kind='warned', report=report, by=moderator, note=note[:300])
    if member and decision in ('suspend', 'age_check', 'ban'):
        kind = {'suspend': 'suspended', 'age_check': 'age_check', 'ban': 'banned'}[decision]
        ModerationAction.objects.create(member=member, kind=kind, report=report, by=moderator, note=note[:300])
        _deactivate(member)

    for r in reports:
        r.resolve(outcome, text, moderator)
    return len(reports)
