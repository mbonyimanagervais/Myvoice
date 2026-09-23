from modules.database import (
    db,
    SystemSetting,
    AuditLog
)

from modules.security import current_organization_id

from datetime import datetime



# =====================================
# CREATE DEFAULT SETTINGS
# =====================================

def create_default_settings(org_id=None):
    """Settings are tenant data. Resolve/create the row bound to the session's
    organization when one exists; otherwise use the legacy global row."""
    from flask import session
    if org_id is None:
        org_id = (
            session.get("organization_id")
            or session.get("voter_org_id")
        )

    if org_id is not None:
        existing = SystemSetting.query.filter_by(
            organization_id=org_id
        ).first()
        if existing is not None:
            return existing

        # Fresh workspace: create a brand-new org-bound settings row instead
        # of falling back to another organization's (or the global) row.
        settings = SystemSetting(
            organization_id=org_id,
            system_name="",
            school_name="",
            school_motto="",
            school_logo="",
            home_image="",
            admin_image="",
            voter_image="",
            dashboard_image="",
            theme="Light",
            primary_color="#0066ff",
            secondary_color="#222222",
            accent_color="#00ff99",
            election_year="",
            default_student_password="",
            footer_text="",
            updated_at=datetime.utcnow()
        )
        db.session.add(settings)
        db.session.commit()
        return settings

    settings = SystemSetting.query.first()


    if settings is None:


        settings = SystemSetting(

            # Admin niwe uzahindura ibi muri Settings UI
            # ntabwo dushyiramo default images


            system_name="",

            school_name="",

            school_motto="",


            school_logo="",

            home_image="",

            admin_image="",

            voter_image="",


            dashboard_image="",



            theme="",



            primary_color="",


            secondary_color="",


            accent_color="",



            election_year="",



            default_student_password="",



            footer_text="",



            updated_at=datetime.utcnow()

        )


        db.session.add(
            settings
        )


        db.session.commit()



    return settings




# =====================================
# GET SYSTEM SETTINGS
# =====================================

def get_settings():

    # Organization-aware: the session context determines which workspace's
    # settings row is returned (admin org, else voter org, else legacy global).
    org_id = current_organization_id()

    if org_id is None:
        from flask import session
        org_id = session.get("voter_org_id")

    if org_id is not None:

        settings = SystemSetting.query.filter_by(
            organization_id=org_id
        ).first()


        if settings is not None:

            return settings


    return create_default_settings()




# =====================================
# UPDATE SETTINGS
# =====================================

def update_settings(data, admin_id=None):


    settings = get_settings()



    settings.system_name = data.get(
        "system_name"
    )


    settings.school_name = data.get(
        "school_name"
    )


    settings.school_motto = data.get(
        "school_motto"
    )



    settings.school_logo = data.get(
        "school_logo"
    )



    settings.home_image = data.get(
        "home_image"
    )



    settings.admin_image = data.get(
        "admin_image"
    )



    settings.voter_image = data.get(
        "voter_image"
    )



    settings.dashboard_image = data.get(
        "dashboard_image"
    )



    settings.theme = data.get(
        "theme"
    )



    settings.primary_color = data.get(
        "primary_color"
    )



    settings.secondary_color = data.get(
        "secondary_color"
    )



    settings.accent_color = data.get(
        "accent_color"
    )



    settings.election_year = data.get(
        "election_year"
    )



    settings.default_student_password = data.get(
        "default_student_password"
    )



    settings.footer_text = data.get(
        "footer_text"
    )



    settings.updated_at = datetime.utcnow()



    # =================================
    # AUDIT LOG
    # =================================

    log = AuditLog(

        organization_id=current_organization_id(),

        user=str(admin_id),

        action="System settings updated"

    )


    db.session.add(
        log
    )



    db.session.commit()



    return settings




# =====================================
# RESET SETTINGS
# =====================================

def reset_settings(admin_id=None):


    settings = get_settings()



    settings.system_name = ""

    settings.school_name = ""

    settings.school_motto = ""

    settings.school_logo = ""

    settings.home_image = ""

    settings.admin_image = ""

    settings.voter_image = ""

    settings.dashboard_image = ""

    settings.theme = ""

    settings.primary_color = ""

    settings.secondary_color = ""

    settings.accent_color = ""

    settings.election_year = ""

    settings.default_student_password = ""

    settings.footer_text = ""



    settings.updated_at = datetime.utcnow()



    log = AuditLog(

        organization_id=current_organization_id(),

        user=str(admin_id),

        action="System settings reset"

    )


    db.session.add(
        log
    )


    db.session.commit()



    return settings