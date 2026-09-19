import pytest

from apps.directory.matching import (
    MAX_RESULTS,
    MatchCriteria,
    haversine_km,
    recommend,
    score_practitioner,
)
from apps.directory.models import HealthConcern, Modality, Practitioner

# Austin city centre, used as the patient's location throughout.
AUSTIN = (30.2672, -97.7431)


@pytest.fixture
def modalities(db):
    return {
        name: Modality.objects.create(name=name)
        for name in ("Acupuncture", "Chiropractic", "Functional Medicine")
    }


@pytest.fixture
def concerns(db, modalities):
    pain = HealthConcern.objects.create(name="Chronic pain")
    pain.modalities.set([modalities["Acupuncture"], modalities["Chiropractic"]])
    fatigue = HealthConcern.objects.create(name="Fatigue")
    fatigue.modalities.set([modalities["Functional Medicine"]])
    sleep = HealthConcern.objects.create(name="Sleep")
    return {"pain": pain, "fatigue": fatigue, "sleep": sleep}


def make_practitioner(name, *, lat=AUSTIN[0], lon=AUSTIN[1], tier="standard", **kwargs):
    modality_list = kwargs.pop("modalities", [])
    concern_list = kwargs.pop("concerns", [])
    practitioner = Practitioner.objects.create(
        display_name=name,
        latitude=lat,
        longitude=lon,
        tier=tier,
        is_published=kwargs.pop("is_published", True),
        **kwargs,
    )
    practitioner.modalities.set(modality_list)
    practitioner.concerns.set(concern_list)
    return practitioner


def criteria_for(concerns=(), modalities=(), **kwargs):
    return MatchCriteria(
        concern_ids={c.id for c in concerns},
        modality_ids={m.id for m in modalities},
        latitude=kwargs.pop("latitude", AUSTIN[0]),
        longitude=kwargs.pop("longitude", AUSTIN[1]),
        **kwargs,
    )


class TestHaversine:
    def test_zero_distance(self):
        assert haversine_km(*AUSTIN, *AUSTIN) == pytest.approx(0, abs=1e-9)

    def test_known_distance_austin_to_denver(self):
        # ~1240 km; generous tolerance since this is a sanity check, not a fixture.
        assert haversine_km(30.2672, -97.7431, 39.7392, -104.9903) == pytest.approx(
            1240, rel=0.02
        )

    def test_is_symmetric(self):
        forward = haversine_km(30.0, -97.0, 31.0, -98.0)
        backward = haversine_km(31.0, -98.0, 30.0, -97.0)
        assert forward == pytest.approx(backward)


@pytest.mark.django_db
class TestScoring:
    def test_concern_match_scores_proportionally(self, concerns):
        both = make_practitioner("Both", concerns=[concerns["pain"], concerns["fatigue"]])
        one = make_practitioner("One", concerns=[concerns["pain"]])

        criteria = criteria_for(concerns=[concerns["pain"], concerns["fatigue"]])

        assert (
            score_practitioner(both, criteria).score
            > score_practitioner(one, criteria).score
        )

    def test_closer_practitioner_outranks_identical_further_one(self, concerns):
        near = make_practitioner("Near", concerns=[concerns["pain"]])
        far = make_practitioner(
            "Far", lat=30.5083, lon=-97.6789, concerns=[concerns["pain"]]
        )

        criteria = criteria_for(concerns=[concerns["pain"]])

        assert (
            score_practitioner(near, criteria).score
            > score_practitioner(far, criteria).score
        )

    def test_practitioner_outside_radius_without_telehealth_is_excluded(self, concerns):
        far = make_practitioner(
            "Denver", lat=39.7392, lon=-104.9903, concerns=[concerns["pain"]]
        )

        assert score_practitioner(far, criteria_for(concerns=[concerns["pain"]])) is None

    def test_distant_telehealth_practitioner_is_kept(self, concerns):
        remote = make_practitioner(
            "Remote",
            lat=39.7392,
            lon=-104.9903,
            offers_telehealth=True,
            concerns=[concerns["pain"]],
        )

        result = score_practitioner(remote, criteria_for(concerns=[concerns["pain"]]))

        assert result is not None
        assert "Available by telehealth" in result.reasons

    def test_telehealth_practitioner_excluded_when_patient_declines_it(self, concerns):
        remote = make_practitioner(
            "Remote",
            lat=39.7392,
            lon=-104.9903,
            offers_telehealth=True,
            concerns=[concerns["pain"]],
        )

        criteria = criteria_for(concerns=[concerns["pain"]], include_telehealth=False)

        assert score_practitioner(remote, criteria) is None

    def test_reasons_explain_the_match(self, concerns, modalities):
        practitioner = make_practitioner(
            "Explained",
            tier="partner",
            concerns=[concerns["pain"]],
            modalities=[modalities["Acupuncture"]],
        )

        result = score_practitioner(
            practitioner,
            criteria_for(
                concerns=[concerns["pain"]], modalities=[modalities["Acupuncture"]]
            ),
        )

        assert "Treats 1 of your 1 concern" in result.reasons
        assert "Offers Acupuncture" in result.reasons
        assert "iamago partner" in result.reasons
        assert any("km away" in reason for reason in result.reasons)


@pytest.mark.django_db
class TestTiers:
    def test_partner_outranks_verified_outranks_standard_when_otherwise_equal(
        self, concerns
    ):
        partner = make_practitioner(
            "A Partner", tier="partner", concerns=[concerns["pain"]]
        )
        verified = make_practitioner(
            "B Verified", tier="verified", concerns=[concerns["pain"]]
        )
        standard = make_practitioner(
            "C Standard", tier="standard", concerns=[concerns["pain"]]
        )

        criteria = criteria_for(concerns=[concerns["pain"]])
        scores = {
            p.display_name: score_practitioner(p, criteria).score
            for p in (partner, verified, standard)
        }

        assert scores["A Partner"] > scores["B Verified"] > scores["C Standard"]

    def test_tier_boost_cannot_beat_a_materially_better_clinical_match(self, concerns):
        """A paying partner matching 1 of 3 concerns must not outrank a
        standard practitioner matching all 3. This is the guardrail that keeps
        paid placement from degrading the recommendations."""
        partner = make_practitioner("Paid", tier="partner", concerns=[concerns["pain"]])
        standard = make_practitioner(
            "Best match",
            tier="standard",
            concerns=[concerns["pain"], concerns["fatigue"], concerns["sleep"]],
        )

        criteria = criteria_for(
            concerns=[concerns["pain"], concerns["fatigue"], concerns["sleep"]]
        )

        assert (
            score_practitioner(standard, criteria).score
            > score_practitioner(partner, criteria).score
        )

    def test_is_preferred_covers_both_badge_tiers(self, concerns):
        assert make_practitioner("P", tier="partner").is_preferred is True
        assert make_practitioner("V", tier="verified").is_preferred is True
        assert make_practitioner("S", tier="standard").is_preferred is False


@pytest.mark.django_db
class TestRecommend:
    def test_returns_at_most_three(self, concerns):
        for index in range(8):
            make_practitioner(f"P{index}", concerns=[concerns["pain"]])

        assert len(recommend(criteria_for(concerns=[concerns["pain"]]))) == MAX_RESULTS

    def test_results_are_ordered_by_score(self, concerns):
        make_practitioner("Weak", concerns=[concerns["pain"]])
        make_practitioner("Strong", tier="partner", concerns=[concerns["pain"]])

        results = recommend(criteria_for(concerns=[concerns["pain"]]))

        assert [r.practitioner.display_name for r in results] == ["Strong", "Weak"]
        assert results[0].score >= results[1].score

    def test_unpublished_practitioners_are_never_recommended(self, concerns):
        make_practitioner("Hidden", is_published=False, concerns=[concerns["pain"]])

        assert recommend(criteria_for(concerns=[concerns["pain"]])) == []

    def test_accepting_new_patients_filter(self, concerns):
        make_practitioner(
            "Closed", accepting_new_patients=False, concerns=[concerns["pain"]]
        )
        make_practitioner(
            "Open", accepting_new_patients=True, concerns=[concerns["pain"]]
        )

        results = recommend(
            criteria_for(concerns=[concerns["pain"]], accepting_new_patients_only=True)
        )

        assert [r.practitioner.display_name for r in results] == ["Open"]

    def test_ordering_is_stable_for_identical_practitioners(self, concerns):
        make_practitioner("Bravo", concerns=[concerns["pain"]])
        make_practitioner("Alpha", concerns=[concerns["pain"]])

        first = [
            r.practitioner.display_name
            for r in recommend(criteria_for(concerns=[concerns["pain"]]))
        ]
        second = [
            r.practitioner.display_name
            for r in recommend(criteria_for(concerns=[concerns["pain"]]))
        ]

        assert first == second == ["Alpha", "Bravo"]

    def test_modality_preference_is_honoured(self, concerns, modalities):
        make_practitioner(
            "Acupuncturist",
            concerns=[concerns["pain"]],
            modalities=[modalities["Acupuncture"]],
        )
        make_practitioner(
            "Chiropractor",
            concerns=[concerns["pain"]],
            modalities=[modalities["Chiropractic"]],
        )

        results = recommend(
            criteria_for(
                concerns=[concerns["pain"]], modalities=[modalities["Acupuncture"]]
            )
        )

        assert results[0].practitioner.display_name == "Acupuncturist"

    def test_narrow_radius_excludes_practitioners_outside_it(self, concerns):
        make_practitioner(
            "Round Rock", lat=30.5083, lon=-97.6789, concerns=[concerns["pain"]]
        )

        assert recommend(criteria_for(concerns=[concerns["pain"]], radius_km=5)) == []
