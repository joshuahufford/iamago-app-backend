"""Seed the directory with demo modalities, concerns and practitioners.

Intended for local development and demos. It is idempotent: running it twice
updates the same records rather than creating duplicates.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.directory.models import HealthConcern, Modality, Practitioner

MODALITIES = [
    (
        "Acupuncture",
        "Thin-needle stimulation of specific points, rooted in East Asian medicine.",
    ),
    (
        "Naturopathic Medicine",
        "Whole-person primary care emphasising nutrition, botanicals and lifestyle.",
    ),
    (
        "Functional Medicine",
        "Root-cause investigation using detailed history and advanced lab testing.",
    ),
    ("Chiropractic", "Hands-on adjustment of the spine and joints to restore movement."),
    (
        "Massage Therapy",
        "Soft-tissue and myofascial work for pain, tension and recovery.",
    ),
    ("Herbal Medicine", "Individualised plant-based formulas, Western or Chinese."),
    (
        "Integrative Nutrition",
        "Food-first care planning alongside conventional treatment.",
    ),
    (
        "Ayurveda",
        "Constitution-based Indian system combining diet, herbs and daily routine.",
    ),
    ("Homeopathy", "Highly diluted remedies matched to the individual picture."),
    ("Mind-Body Therapy", "Somatic, breathwork and nervous-system regulation practices."),
    (
        "Osteopathic Manipulation",
        "Gentle manual techniques applied by an osteopathic physician.",
    ),
    (
        "Integrative Psychiatry",
        "Mental health care combining conventional and complementary approaches.",
    ),
]

# concern name -> (description, modality names typically used for it)
CONCERNS = {
    "Chronic pain": (
        "Persistent pain lasting more than three months.",
        ["Acupuncture", "Chiropractic", "Massage Therapy", "Osteopathic Manipulation"],
    ),
    "Fatigue & low energy": (
        "Ongoing tiredness that rest does not resolve.",
        ["Functional Medicine", "Naturopathic Medicine", "Integrative Nutrition"],
    ),
    "Digestive & gut health": (
        "Bloating, IBS, reflux and related complaints.",
        ["Functional Medicine", "Integrative Nutrition", "Herbal Medicine", "Ayurveda"],
    ),
    "Hormonal & thyroid": (
        "Thyroid, adrenal and sex-hormone imbalance.",
        ["Functional Medicine", "Naturopathic Medicine", "Herbal Medicine"],
    ),
    "Autoimmune conditions": (
        "Hashimoto's, RA, lupus and related diagnoses.",
        ["Functional Medicine", "Naturopathic Medicine", "Integrative Nutrition"],
    ),
    "Anxiety & stress": (
        "Persistent worry, overwhelm and nervous-system dysregulation.",
        ["Mind-Body Therapy", "Acupuncture", "Integrative Psychiatry", "Herbal Medicine"],
    ),
    "Sleep problems": (
        "Trouble falling asleep, staying asleep or waking rested.",
        ["Acupuncture", "Mind-Body Therapy", "Herbal Medicine", "Ayurveda"],
    ),
    "Women's health": (
        "Cycle, fertility, perimenopause and menopause care.",
        ["Naturopathic Medicine", "Acupuncture", "Functional Medicine"],
    ),
    "Allergies & immunity": (
        "Seasonal allergies and frequent infections.",
        ["Homeopathy", "Naturopathic Medicine", "Herbal Medicine"],
    ),
    "Longevity & prevention": (
        "Staying well and ageing on your own terms.",
        ["Functional Medicine", "Integrative Nutrition", "Ayurveda"],
    ),
    "Injury recovery": (
        "Getting back to full movement after injury or surgery.",
        ["Massage Therapy", "Chiropractic", "Osteopathic Manipulation", "Acupuncture"],
    ),
    "Headaches & migraine": (
        "Recurring head pain and migraine patterns.",
        ["Acupuncture", "Chiropractic", "Functional Medicine", "Mind-Body Therapy"],
    ),
}

# (name, credentials, practice, city, region, postal, lat, lon, tier,
#  modalities, concerns, telehealth, accepting, insurance, years)
PRACTITIONERS = [
    (
        "Maya Ellison",
        "LAc, DACM",
        "Still Point Acupuncture",
        "Austin",
        "TX",
        "78704",
        30.2500,
        -97.7500,
        "partner",
        ["Acupuncture", "Herbal Medicine"],
        ["Chronic pain", "Anxiety & stress", "Sleep problems", "Headaches & migraine"],
        True,
        True,
        False,
        12,
    ),
    (
        "Daniel Ortiz",
        "ND",
        "Cedar & Root Naturopathic",
        "Austin",
        "TX",
        "78702",
        30.2700,
        -97.7100,
        "verified",
        ["Naturopathic Medicine", "Integrative Nutrition"],
        ["Fatigue & low energy", "Digestive & gut health", "Hormonal & thyroid"],
        True,
        True,
        True,
        9,
    ),
    (
        "Priya Raghunathan",
        "MD, IFMCP",
        "Lumen Functional Medicine",
        "Austin",
        "TX",
        "78746",
        30.2900,
        -97.8100,
        "partner",
        ["Functional Medicine", "Integrative Nutrition"],
        [
            "Autoimmune conditions",
            "Hormonal & thyroid",
            "Longevity & prevention",
            "Fatigue & low energy",
        ],
        True,
        True,
        False,
        15,
    ),
    (
        "Corey Whitfield",
        "DC",
        "Barton Springs Chiropractic",
        "Austin",
        "TX",
        "78704",
        30.2580,
        -97.7660,
        "standard",
        ["Chiropractic", "Massage Therapy"],
        ["Chronic pain", "Injury recovery", "Headaches & migraine"],
        False,
        True,
        True,
        7,
    ),
    (
        "Nadia Farouk",
        "LMT, CST",
        "Quiet Hands Bodywork",
        "Austin",
        "TX",
        "78751",
        30.3100,
        -97.7200,
        "standard",
        ["Massage Therapy", "Mind-Body Therapy"],
        ["Chronic pain", "Anxiety & stress", "Injury recovery"],
        False,
        False,
        False,
        5,
    ),
    (
        "Ravi Chandrasekar",
        "BAMS",
        "Soma Ayurveda",
        "Austin",
        "TX",
        "78745",
        30.2200,
        -97.7900,
        "verified",
        ["Ayurveda", "Herbal Medicine", "Integrative Nutrition"],
        ["Digestive & gut health", "Sleep problems", "Longevity & prevention"],
        True,
        True,
        False,
        18,
    ),
    (
        "Helen Marsh",
        "DO",
        "Round Rock Osteopathic",
        "Round Rock",
        "TX",
        "78664",
        30.5083,
        -97.6789,
        "standard",
        ["Osteopathic Manipulation", "Chiropractic"],
        ["Chronic pain", "Injury recovery"],
        False,
        True,
        True,
        20,
    ),
    (
        "Tomas Lindgren",
        "MD",
        "Northwest Integrative Psychiatry",
        "Austin",
        "TX",
        "78759",
        30.4000,
        -97.7500,
        "verified",
        ["Integrative Psychiatry", "Mind-Body Therapy"],
        ["Anxiety & stress", "Sleep problems"],
        True,
        True,
        True,
        11,
    ),
    (
        "Grace Okonkwo",
        "ND, LAc",
        "Willow Clinic",
        "Denver",
        "CO",
        "80206",
        39.7300,
        -104.9500,
        "partner",
        ["Naturopathic Medicine", "Acupuncture"],
        ["Women's health", "Hormonal & thyroid", "Fatigue & low energy"],
        True,
        True,
        False,
        14,
    ),
    (
        "Samuel Reyes",
        "DC",
        "Front Range Spine",
        "Denver",
        "CO",
        "80211",
        39.7650,
        -105.0200,
        "standard",
        ["Chiropractic"],
        ["Chronic pain", "Injury recovery"],
        False,
        True,
        True,
        6,
    ),
    (
        "Ana Beltrán",
        "CNS",
        "Mile High Nutrition",
        "Denver",
        "CO",
        "80202",
        39.7500,
        -105.0000,
        "verified",
        ["Integrative Nutrition", "Functional Medicine"],
        ["Digestive & gut health", "Autoimmune conditions", "Longevity & prevention"],
        True,
        True,
        False,
        8,
    ),
    (
        "Jonah Feldman",
        "LAc",
        "Hudson Acupuncture",
        "New York",
        "NY",
        "10011",
        40.7400,
        -74.0000,
        "partner",
        ["Acupuncture", "Herbal Medicine"],
        ["Anxiety & stress", "Headaches & migraine", "Sleep problems"],
        False,
        True,
        False,
        16,
    ),
    (
        "Rebecca Stein",
        "ND",
        "Gramercy Naturopathic",
        "New York",
        "NY",
        "10010",
        40.7380,
        -73.9830,
        "standard",
        ["Naturopathic Medicine", "Homeopathy"],
        ["Allergies & immunity", "Digestive & gut health"],
        True,
        False,
        False,
        10,
    ),
    (
        "Wei Chen",
        "DACM, LAc",
        "Telehealth Herbal Practice",
        "Seattle",
        "WA",
        "98101",
        47.6100,
        -122.3300,
        "verified",
        ["Herbal Medicine", "Acupuncture"],
        ["Fatigue & low energy", "Digestive & gut health", "Women's health"],
        True,
        True,
        False,
        13,
    ),
]


class Command(BaseCommand):
    help = "Seed demo modalities, health concerns and practitioners."

    def add_arguments(self, parser):
        parser.add_argument(
            "--flush",
            action="store_true",
            help="Delete existing practitioners before seeding.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        if options["flush"]:
            count, _ = Practitioner.objects.all().delete()
            self.stdout.write(f"Deleted {count} existing practitioner rows.")

        modalities = {}
        for order, (name, description) in enumerate(MODALITIES):
            modality, _ = Modality.objects.update_or_create(
                name=name, defaults={"description": description, "sort_order": order}
            )
            modalities[name] = modality

        concerns = {}
        for order, (name, (description, modality_names)) in enumerate(CONCERNS.items()):
            concern, _ = HealthConcern.objects.update_or_create(
                name=name, defaults={"description": description, "sort_order": order}
            )
            concern.modalities.set([modalities[n] for n in modality_names])
            concerns[name] = concern

        for row in PRACTITIONERS:
            (
                name,
                credentials,
                practice,
                city,
                region,
                postal,
                lat,
                lon,
                tier,
                modality_names,
                concern_names,
                telehealth,
                accepting,
                insurance,
                years,
            ) = row

            practitioner, _ = Practitioner.objects.update_or_create(
                display_name=name,
                defaults={
                    "credentials": credentials,
                    "practice_name": practice,
                    "bio": (
                        f"{name} has practised for {years} years at {practice} in "
                        f"{city}, {region}."
                    ),
                    "city": city,
                    "region": region,
                    "postal_code": postal,
                    "country": "US",
                    "latitude": lat,
                    "longitude": lon,
                    "tier": tier,
                    "offers_telehealth": telehealth,
                    "accepting_new_patients": accepting,
                    "accepts_insurance": insurance,
                    "years_experience": years,
                    "is_published": True,
                    "website": f"https://example.com/{name.lower().replace(' ', '-')}",
                    "phone": "+1 512 555 0100",
                },
            )
            practitioner.modalities.set([modalities[n] for n in modality_names])
            practitioner.concerns.set([concerns[n] for n in concern_names])

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {len(modalities)} modalities, {len(concerns)} concerns and "
                f"{len(PRACTITIONERS)} practitioners."
            )
        )
