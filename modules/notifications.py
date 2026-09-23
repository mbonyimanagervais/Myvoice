from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash
)

from modules.database import (
    db,
    Notification,
    AuditLog
)

from modules.auth import admin_required
from modules.security import (
    current_organization_id,
    org_scoped_get
)



notifications = Blueprint(
    "notifications",
    __name__
)



# ======================================
# VIEW NOTIFICATIONS
# ======================================

@notifications.route(
    "/admin/notifications"
)
@admin_required
def notifications_page():


    # Organization isolation: administrators manage only their own notices.
    all_notifications = Notification.query.filter_by(
        organization_id=current_organization_id()
    ).order_by(
        Notification.id.desc()
    ).all()



    return render_template(
        "notifications.html",
        notifications=all_notifications
    )



# ======================================
# CREATE NOTIFICATION
# ======================================

@notifications.route(
    "/admin/notifications/add",
    methods=[
        "POST"
    ]
)
@admin_required
def add_notification():


    message = request.form.get(
        "message"
    )



    notification = Notification(

        organization_id=current_organization_id(),

        message=message

    )



    db.session.add(
        notification
    )



    log = AuditLog(

        organization_id=current_organization_id(),

        user="ADMIN",

        action="Created notification"

    )


    db.session.add(
        log
    )



    db.session.commit()



    flash(
        "Notification created successfully",
        "success"
    )


    return redirect(
        url_for(
            "notifications.notifications_page"
        )
    )



# ======================================
# DELETE NOTIFICATION
# ======================================

@notifications.route(
    "/admin/notifications/delete/<int:id>"
)
@admin_required
def delete_notification(id):


    notification = org_scoped_get(Notification, id)



    db.session.delete(
        notification
    )



    log = AuditLog(

        organization_id=current_organization_id(),

        user="ADMIN",

        action="Deleted notification"

    )


    db.session.add(
        log
    )



    db.session.commit()



    flash(
        "Notification deleted",
        "success"
    )


    return redirect(
        url_for(
            "notifications.notifications_page"
        )
    )



# ======================================
# PUBLIC NOTIFICATIONS API
# ======================================

@notifications.route(
    "/api/notifications"
)
def api_notifications():


    # Public API used by the voting/home pages. Scope strictly to the
    # authenticated session's organization; anonymous visitors only ever see
    # platform-wide (organization-less) announcements — never tenant data.
    org_id = session.get("organization_id") or session.get("voter_org_id")

    if org_id is not None:
        data = Notification.query.filter_by(
            organization_id=org_id
        ).order_by(
            Notification.id.desc()
        ).all()
    else:
        data = Notification.query.filter(
            Notification.organization_id.is_(None)
        ).order_by(
            Notification.id.desc()
        ).all()



    return {

        "notifications":[

            {

                "id": item.id,

                "message": item.message,

                "created_at": item.created_at.strftime(
                    "%Y-%m-%d %H:%M"
                )

            }

            for item in data

        ]

    }