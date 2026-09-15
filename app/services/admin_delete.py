"""Hard delete for the admin panel: permanent, cascading removal of a post or a user.

This does NOT rely on database-level ON DELETE behaviour (some FKs cascade, many don't, and
they were added incrementally across several phases) - every dependent row is deleted or
anonymised explicitly, in dependency order, inside one transaction the caller commits.
Nothing here is reversible; callers are responsible for confirming intent first.
"""
from app import db


def _delete_matches_for_trip_ids(trip_ids):
    """Remove every Match touching any of these posts, plus its parties and reports."""
    from app.models import Match, MatchParty, MatchReport
    if not trip_ids:
        return
    match_ids = [m.id for m in Match.query.filter(
        db.or_(Match.trip_a_id.in_(trip_ids), Match.trip_b_id.in_(trip_ids))).all()]
    if match_ids:
        MatchReport.query.filter(MatchReport.match_id.in_(match_ids)).delete(synchronize_session=False)
        MatchParty.query.filter(MatchParty.match_id.in_(match_ids)).delete(synchronize_session=False)
        Match.query.filter(Match.id.in_(match_ids)).delete(synchronize_session=False)


def delete_post_cascade(trip):
    """Permanently delete one CompanionRequest and everything that only makes sense with it."""
    from app.models import (ContactPoint, ClaimToken, ConnectionRequest, ChatRoom, ChatMessage,
                            ActivityEvent, TripLeg, Notification, ScrapeRow)
    trip_id = trip.id

    _delete_matches_for_trip_ids([trip_id])

    conn_ids = [c.id for c in ConnectionRequest.query.filter_by(trip_id=trip_id).all()]
    if conn_ids:
        Notification.query.filter(Notification.connection_id.in_(conn_ids)) \
            .update({'connection_id': None}, synchronize_session=False)
        ConnectionRequest.query.filter(ConnectionRequest.id.in_(conn_ids)).delete(synchronize_session=False)

    room_ids = [r.id for r in ChatRoom.query.filter_by(trip_id=trip_id).all()]
    if room_ids:
        ChatMessage.query.filter(ChatMessage.room_id.in_(room_ids)).delete(synchronize_session=False)
        ChatRoom.query.filter(ChatRoom.id.in_(room_ids)).delete(synchronize_session=False)

    ContactPoint.query.filter_by(trip_id=trip_id).delete(synchronize_session=False)
    ClaimToken.query.filter_by(trip_id=trip_id).delete(synchronize_session=False)
    ActivityEvent.query.filter_by(trip_id=trip_id).delete(synchronize_session=False)
    TripLeg.query.filter_by(trip_id=trip_id).delete(synchronize_session=False)
    ScrapeRow.query.filter_by(duplicate_of_id=trip_id).update({'duplicate_of_id': None}, synchronize_session=False)
    ScrapeRow.query.filter_by(imported_post_id=trip_id).update({'imported_post_id': None}, synchronize_session=False)

    db.session.delete(trip)


def delete_user_cascade(user):
    """Permanently delete a user: their posts (and everything tied to those posts, via
    delete_post_cascade), their own direct records, and anonymise incidental references
    left in other people's history (who sent a claim link, who reported a match, ...)."""
    from app.models import (CompanionRequest, Feedback, ChatRoom, ChatMessage, Notification,
                            ConnectionRequest, ContactPoint, ActivityEvent, ClaimToken,
                            MatchParty, Match, MatchReport, Blog)
    user_id = user.id

    for trip in CompanionRequest.query.filter_by(user_id=user_id).all():
        delete_post_cascade(trip)

    Feedback.query.filter_by(user_id=user_id).delete(synchronize_session=False)
    Blog.query.filter_by(author_id=user_id).delete(synchronize_session=False)

    room_ids = [r.id for r in ChatRoom.query.filter(
        db.or_(ChatRoom.user1_id == user_id, ChatRoom.user2_id == user_id)).all()]
    if room_ids:
        ChatMessage.query.filter(ChatMessage.room_id.in_(room_ids)).delete(synchronize_session=False)
        ChatRoom.query.filter(ChatRoom.id.in_(room_ids)).delete(synchronize_session=False)

    Notification.query.filter_by(user_id=user_id).delete(synchronize_session=False)
    ConnectionRequest.query.filter_by(requester_id=user_id).delete(synchronize_session=False)
    ContactPoint.query.filter_by(user_id=user_id).delete(synchronize_session=False)

    # incidental references: this person acted on / was mentioned in someone ELSE's record -
    # anonymise rather than delete, so the other person's history stays intact.
    ActivityEvent.query.filter_by(actor_id=user_id).update({'actor_id': None}, synchronize_session=False)
    ClaimToken.query.filter_by(created_by_id=user_id).update({'created_by_id': None}, synchronize_session=False)
    MatchParty.query.filter_by(sent_by_id=user_id).update({'sent_by_id': None}, synchronize_session=False)
    Match.query.filter_by(cs_owner_id=user_id).update({'cs_owner_id': None}, synchronize_session=False)
    MatchReport.query.filter_by(reporter_id=user_id).update({'reporter_id': None}, synchronize_session=False)
    MatchReport.query.filter_by(resolved_by_id=user_id).update({'resolved_by_id': None}, synchronize_session=False)
    CompanionRequest.query.filter_by(closed_by_id=user_id).update({'closed_by_id': None}, synchronize_session=False)

    try:
        from app.models import ScrapeRow, ScrapeRecipe, ScrapeRun
        ScrapeRow.query.filter_by(imported_by_id=user_id).update({'imported_by_id': None}, synchronize_session=False)
        ScrapeRecipe.query.filter_by(created_by_id=user_id).update({'created_by_id': None}, synchronize_session=False)
        ScrapeRun.query.filter_by(started_by_id=user_id).update({'started_by_id': None}, synchronize_session=False)
    except ImportError:      # pragma: no cover - scraper models optional
        pass

    db.session.delete(user)
