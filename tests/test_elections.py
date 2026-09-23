import unittest

from app import app
from modules.database import db, Election, Position
from modules.elections import validate_election


class ElectionValidationTests(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        self.app_context = app.app_context()
        self.app_context.push()
        db.drop_all()
        db.create_all()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def test_validation_detects_duplicate_positions(self):
        election = Election(
            organization_id=None,
            title='Test Election',
            description='Demo',
            election_year='2026',
            status='Draft'
        )
        db.session.add(election)
        db.session.flush()

        db.session.add_all([
            Position(organization_id=None, name='President', election_id=election.id),
            Position(organization_id=None, name='President', election_id=election.id)
        ])
        db.session.commit()

        with app.test_request_context():
            from flask import session
            session['organization_id'] = None
            issues = validate_election(election)
        self.assertIn('Duplicate positions found', issues)


if __name__ == '__main__':
    unittest.main()
