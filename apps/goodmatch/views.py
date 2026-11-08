"""
A Good Match API (members who opted in only).

GET    /api/match/                        the screen: off | paused | cool | browse | locked | met
POST   /api/match/decide/                 {user, action: like|pass, prompt?, note?}
GET    /api/match/profile/                your match profile and preferences
PATCH  /api/match/profile/
POST   /api/match/<id>/suggest/           {event?} suggest a first meetup (DELETE takes it back)
POST   /api/match/<id>/met/               "We met up"
POST   /api/match/<id>/keep/              "Keep seeing them"
POST   /api/match/<id>/open/              "Open up to new matches"
POST   /api/match/<id>/move-on/           "I've changed my mind" (cooldown until 9:00 AM)
"""

from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from . import services as svc


def _bad(e):
    return Response({'code': e.code, 'message': e.message}, status=e.http)


def _off():
    return Response({'code': 'not_opted_in', 'message': 'Turn on Romantic to use A Good Match.'},
                    status=status.HTTP_403_FORBIDDEN)


class StateView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response(svc.state(request.user, request))


class DecideView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        if not svc.opted_in(request.user):
            return _off()
        d = request.data
        try:
            target = int(d.get('user'))
        except (TypeError, ValueError):
            return Response({'code': 'user', 'message': 'Missing who.'}, status=400)
        try:
            m = svc.decide(request.user, target, d.get('action'), d.get('prompt', ''), d.get('note', ''))
        except svc.NotAllowed as e:
            return _bad(e)
        return Response(dict(svc.state(request.user, request), matched=m is not None))


class ProfileView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        if not svc.opted_in(request.user):
            return _off()
        return Response(svc.profile_payload(request.user))

    def patch(self, request):
        if not svc.opted_in(request.user):
            return _off()
        try:
            return Response(svc.update_profile(request.user, request.data))
        except svc.NotAllowed as e:
            return _bad(e)


class _MatchAction(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        try:
            m = svc.get_match(request.user, pk)
            self.run(request, m)
        except svc.NotAllowed as e:
            return _bad(e)
        return Response(svc.state(request.user, request))

    def run(self, request, m):
        raise NotImplementedError


class SuggestView(_MatchAction):
    def run(self, request, m):
        svc.suggest(request.user, m, request.data.get('event'))

    def delete(self, request, pk):
        try:
            svc.unsuggest(request.user, svc.get_match(request.user, pk))
        except svc.NotAllowed as e:
            return _bad(e)
        return Response(svc.state(request.user, request))


class MetView(_MatchAction):
    def run(self, request, m):
        svc.met_up(request.user, m)


class KeepView(_MatchAction):
    def run(self, request, m):
        svc.keep(request.user, m)


class OpenView(_MatchAction):
    def run(self, request, m):
        svc.open_up(request.user, m)


class MoveOnView(_MatchAction):
    def run(self, request, m):
        svc.move_on(request.user, m)
