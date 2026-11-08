"""Public Community Guidelines and Featured Events Policy pages (linked
from business sign-up). The guidelines copy matches the app
(lib/content/community_guidelines.dart)."""

from django.shortcuts import render

GUIDELINES = [
    ('Show up with respect', 'Every pace, body and background belongs here.', [
        'No harassment, hate speech or body shaming, in chats or on the road.',
        'Cheer people on. Kudos and comments should lift people up.',
        'Disagree kindly, and take it private if it gets heated.']),
    ('Move safely together', 'Group rides only work when everyone looks out for each other.', [
        'Follow ride leaders, traffic laws and the posted pace.',
        'No-drop rides mean no one gets left behind.',
        'Helmets on every club ride. Lights after dark.']),
    ('Keep chats on topic', 'Ride chats belong to one event and close 48 hours after it ends.', [
        'Slow mode: more than 3 messages in 20 seconds pauses you for 30 seconds.',
        'No promos, sales or links to other groups without an organizer’s OK.',
        'Keep side conversations in direct messages.']),
    ('Respect privacy', 'What people share with the crew stays with the crew.', [
        'Ask before posting photos of someone else.',
        'Never share anyone’s address, live location or routine.',
        'Set a privacy zone around home so your maps start down the block.']),
    ('A Good Match is opt-in', 'Dating lives in its own space, only for people who turned it on.', [
        'Never bring matches or dating into club chats or rides.',
        'One match at a time. A no, or no reply, is an answer.',
        'Meet somewhere public for the first meetup and tell a friend.']),
    ('Keep it real', 'Your profile and your activities should be honestly you.', [
        'Use a real photo and your real name.',
        'Log activities honestly. Car rides don’t count toward segments.',
        'You must be 21 or older, with one account per person.']),
    ('If something’s off, report it', 'Tap Report on any message, profile or match. A real person reviews it within '
     '24 hours, and the person never finds out it was you. In danger? Call 911 first.', []),
]

FEATURED = [
    ('Every featured event is labeled', 'Members always know what’s paid.', [
        'Featured events carry a “Featured” label and a “Why am I seeing this?” note that says who paid and why '
        'it’s shown.']),
    ('A person reviews every event', 'Nothing goes live without a review, usually within 1 business day.', [
        'It follows the Community Guidelines.',
        'The details are accurate: what it is, when, where and what it costs.',
        'It’s run by a real, verified business.']),
    ('Where featured events appear', 'Only in places members go to find things to do.', [
        'The top slot on Events, a card in Home feeds and, on the Partner plan, the Community hub.',
        'Never in ride chats, direct messages, match chats or A Good Match.']),
    ('Who sees them', 'Targeting uses only neighborhood and the interests members chose.', [
        'Never dating status, age or health data.']),
    ('What you see afterwards', 'Counts and percentages, never personal information.', [
        'Breakdowns smaller than 10 people are grouped as “Other” so no one can be singled out.',
        'A member’s name is shared with you only if they choose to share it when they check in.']),
    ('Billing', 'You’re only charged once your event is approved.', [
        'Spotlight and Boost are charged once per event. The Partner plan is billed monthly and includes up to '
        '4 featured events a month.']),
]


def _page(request, title, lede, sections, short='', foot=''):
    return render(request, 'policies/page.html', {
        'title': title, 'lede': lede, 'short': short, 'version': '2026-11',
        'sections': [{'title': t, 'summary': s, 'points': p} for t, s, p in sections],
        'foot': foot,
    })


def guidelines(request):
    return _page(request, 'Community Guidelines',
                 'How we keep A Good Fit a good place to move, meet and look out for each other.', GUIDELINES,
                 short='Show up. Look out. Keep it kind.',
                 foot='These apply everywhere in the app, from the feed to ride chats to A Good Match.')


def featured_policy(request):
    return _page(request, 'Featured Events Policy',
                 'Businesses can pay to feature events on A Good Fit. Here’s how that works, for them and for '
                 'members.', FEATURED,
                 foot='Featured events also follow the Community Guidelines. This policy is pending legal review.')
