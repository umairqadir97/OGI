"""The supplied pilot is a source record. Reuse examples are explicitly simulated."""

PROMPT = "Using only the supplied observations and the checklist, produce a review queue with source IDs, possible grouping, status, missing evidence, next action, and owner. Treat observations as unconfirmed. Do not invent screenshots or measurements. Merge only when the same element, state, and requirement are established."

INITIAL_AI_PILOT_EXCERPT = (
    "AI Pilot Raw Run (Phase 1B): 40 observations generated. Preliminary triage proposed merging "
    "F1 (Header on Standard-to-Premium) and F2 (Headline on Premium) as a unified defect based on 390px text match. "
    "F4 flagged as non-compliant with 18px mobile rule without element identification or computed pixel measurement. "
    "[Pre-Flight Gate Action: Prevented premature defect logging; enforced element/viewport crop verification]."
)

SCENARIOS = {
    "VISUAL_QA": {
        "name": "Visual QA · Phase 1B",
        "department": "Product & design",
        "simulated": False,
        "description": "Puffy upgrade experience · Standard to Premium",
        "checklist_rules": [
            "Mobile text minimum 18px.",
            "Spacing, alignment, and visible elements must match the approved design across screen sizes.",
            "Real-device checks must supplement responsive viewers.",
            "Copy and feature order require Product Owner confirmation.",
        ],
        "raw_items": [
            {
                "id": "F1",
                "author": "Reviewer A",
                "comment_text": "Header is nearly edge to edge at 390px on the Standard-to-Premium upgrade popup.",
            },
            {
                "id": "F2",
                "author": "Reviewer B",
                "comment_text": "Headline looks too tight on the Premium upgrade popup at a 390px viewport.",
            },
            {
                "id": "F3",
                "author": "Reviewer B",
                "comment_text": "Update the timer label to 'HOURS'.",
            },
            {
                "id": "F4",
                "author": "Reviewer A",
                "comment_text": "Increase the font size to 18px. The text comment does not identify the element or viewport.",
            },
            {
                "id": "F5",
                "author": "Reviewer C",
                "comment_text": "Remove the divider when scrolling is not required.",
            },
            {
                "id": "F6",
                "author": "Reviewer B",
                "comment_text": "Switch items 3 and 4 on the Premium upgrade card to match the feature order on Standard.",
            },
        ],
    },
    "CRO_HYPOTHESIS": {
        "name": "CRO hypothesis gate",
        "department": "Digital Experience & Conversion",
        "simulated": True,
        "description": "Simulated cross-department reuse · Experiment brief",
        "checklist_rules": [
            "Name the audience, control, and proposed change.",
            "Provide a sourced baseline and primary success metric.",
            "Define sample size, stop conditions, and guardrail metrics before launch.",
            "Validate statistical MDE calculation and mobile CTA fold hierarchy.",
        ],
        "raw_items": [
            {
                "id": "C1",
                "author": "DX team",
                "comment_text": "Move the trial CTA above the fold to improve conversion by 15%.",
            },
            {
                "id": "C2",
                "author": "Experiment owner",
                "comment_text": "Test a shorter checkout with returning mobile visitors at 390px. Primary metric: completed purchases.",
            },
            {
                "id": "C3",
                "author": "DX team",
                "comment_text": "Stop the test after one week if the new layout is winning.",
            },
            {
                "id": "C4",
                "author": "Conversion specialist",
                "comment_text": "Saatva vs. Puffy comparison table header missing independent coil count verification.",
            },
        ],
    },
    "PPC_COPY": {
        "name": "PPC claim gate",
        "department": "Paid media team",
        "simulated": True,
        "description": "Simulated cross-department reuse · Search ad claims",
        "checklist_rules": [
            "Product claims require a current approved truth-pack source.",
            "Absolute or comparative claims require substantiation.",
            "Offer terms, landing-page consistency, and headline length require review.",
            "SKU specifications (coils, foams, warranty) must match Puffy Product Master.",
        ],
        "raw_items": [
            {
                "id": "P1",
                "author": "Paid media",
                "comment_text": "The world's best mattress. Guaranteed to cure back pain.",
            },
            {
                "id": "P2",
                "author": "Paid media",
                "comment_text": "Save 40% today — free delivery on every order with 365-night trial.",
            },
            {
                "id": "P3",
                "author": "Paid media",
                "comment_text": "Puffy Cloud memory foam features individually wrapped pocketed coils.",
            },
            {
                "id": "P4",
                "author": "Paid media",
                "comment_text": "Find your comfort. Explore the Premium collection with cooling gel.",
            },
        ],
    },
    "TRIALSAVE_365": {
        "name": "TrialSave-365 warranty gate",
        "department": "Customer Operations & Warranty",
        "simulated": True,
        "description": "Sleep-trial & warranty resolution · Comfort layer exchange",
        "checklist_rules": [
            "Confirm customer trial day count (Day 30–365) and verified mattress model.",
            "Lower back firmness issues qualify for $0 Orthopedic Topper concession (cap <= $250) before $2,249 refund authorization.",
            "Structural warranty claims require photo verification on flat foundation.",
            "Minimum 30-night break-in period required before return initiation.",
        ],
        "raw_items": [
            {
                "id": "T1",
                "author": "CX agent",
                "comment_text": "Customer ticket #8821: Day 82 Puffy Lux Hybrid customer experiencing lower back soreness. Requesting full $2,249 refund.",
            },
            {
                "id": "T2",
                "author": "CX agent",
                "comment_text": "Customer ticket #8845: Day 14 Puffy Cloud customer wants immediate carrier pickup before 30-night break-in period.",
            },
            {
                "id": "T3",
                "author": "Warranty lead",
                "comment_text": "Customer ticket #8912: Sagging claim on 3-year-old Puffy Royal. Foundation photo shows slatted base with 5-inch gaps.",
            },
        ],
    },
}

BENCHMARK_TRIAL_DATA = {
    "trial_tasks": [
        {
            "task_id": "Task-01-HeaderModal",
            "manual_baseline_mins": 84.0,
            "prep_mins": 18.0,
            "ai_mins": 14.0,
            "review_mins": 12.0,
            "logging_mins": 8.0,
            "rework_mins": 8.0,
            "major_misses_baseline": 1,
            "major_misses_assisted": 0,
            "comparable_scope_confirmed": True,
        },
        {
            "task_id": "Task-02-CheckoutCart",
            "manual_baseline_mins": 90.0,
            "prep_mins": 20.0,
            "ai_mins": 15.0,
            "review_mins": 14.0,
            "logging_mins": 6.0,
            "rework_mins": 9.0,
            "major_misses_baseline": 2,
            "major_misses_assisted": 1,
            "comparable_scope_confirmed": True,
        },
        {
            "task_id": "Task-03-PDPPricingGrid",
            "manual_baseline_mins": 82.0,
            "prep_mins": 16.0,
            "ai_mins": 13.0,
            "review_mins": 10.0,
            "logging_mins": 5.0,
            "rework_mins": 10.0,
            "major_misses_baseline": 0,
            "major_misses_assisted": 0,
            "comparable_scope_confirmed": True,
        },
        {
            "task_id": "Task-04-NavDrawerMobile",
            "manual_baseline_mins": 85.0,
            "prep_mins": 19.0,
            "ai_mins": 14.0,
            "review_mins": 12.0,
            "logging_mins": 7.0,
            "rework_mins": 8.0,
            "major_misses_baseline": 1,
            "major_misses_assisted": 1,
            "comparable_scope_confirmed": True,
        },
        {
            "task_id": "Task-05-StandardUpgradeCard",
            "manual_baseline_mins": 84.0,
            "prep_mins": 18.0,
            "ai_mins": 14.0,
            "review_mins": 11.0,
            "logging_mins": 6.0,
            "rework_mins": 9.0,
            "major_misses_baseline": 1,
            "major_misses_assisted": 0,
            "comparable_scope_confirmed": True,
        },
        {
            "task_id": "Task-06-TimerStickyBar",
            "manual_baseline_mins": 78.0,
            "prep_mins": 15.0,
            "ai_mins": 12.0,
            "review_mins": 10.0,
            "logging_mins": 6.0,
            "rework_mins": 7.0,
            "major_misses_baseline": 0,
            "major_misses_assisted": 0,
            "comparable_scope_confirmed": True,
        },
        {
            "task_id": "Task-07-ReviewsWidgetEmbed",
            "manual_baseline_mins": 88.0,
            "prep_mins": 20.0,
            "ai_mins": 16.0,
            "review_mins": 13.0,
            "logging_mins": 7.0,
            "rework_mins": 10.0,
            "major_misses_baseline": 2,
            "major_misses_assisted": 1,
            "comparable_scope_confirmed": True,
        },
        {
            "task_id": "Task-08-FooterCompliance",
            "manual_baseline_mins": 76.0,
            "prep_mins": 14.0,
            "ai_mins": 11.0,
            "review_mins": 9.0,
            "logging_mins": 5.0,
            "rework_mins": 8.0,
            "major_misses_baseline": 0,
            "major_misses_assisted": 0,
            "comparable_scope_confirmed": True,
        },
        {
            "task_id": "Task-09-ComparisonTableSaatva",
            "manual_baseline_mins": 92.0,
            "prep_mins": 22.0,
            "ai_mins": 16.0,
            "review_mins": 14.0,
            "logging_mins": 8.0,
            "rework_mins": 11.0,
            "major_misses_baseline": 2,
            "major_misses_assisted": 1,
            "comparable_scope_confirmed": True,
        },
        {
            "task_id": "Task-10-WarrantyBadgePopup",
            "manual_baseline_mins": 80.0,
            "prep_mins": 16.0,
            "ai_mins": 12.0,
            "review_mins": 10.0,
            "logging_mins": 6.0,
            "rework_mins": 8.0,
            "major_misses_baseline": 1,
            "major_misses_assisted": 0,
            "comparable_scope_confirmed": True,
        },
    ],
    "release_cycles": [
        {
            "cycle_id": "Cycle 1",
            "baseline_escaped_defects": 4,
            "assisted_escaped_defects": 3,
        },
        {
            "cycle_id": "Cycle 2",
            "baseline_escaped_defects": 5,
            "assisted_escaped_defects": 4,
        },
    ],
}
