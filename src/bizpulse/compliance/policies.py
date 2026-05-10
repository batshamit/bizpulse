"""Static registry of regulations a marketing recommendation can hit.

Coverage today (~30 entries):
  - India central: RBI digital lending, SEBI advertising, IRDAI ads,
    DPDP Act, Consumer Protection (misleading ads), GST, ASCI Code,
    TRAI TCCCPR, FEMA NRI rules.
  - India state: RERA Maharashtra / Karnataka / Tamil Nadu / Delhi / UP
    (template — easy to add more states).
  - India industry-specific: BIS / IS codes, GRIHA, IGBC, MoEF (env clearances).
  - EU: GDPR, MiFID II, DSA, AI Act, ePrivacy, eIDAS.
  - US: SEC investor advertising, FTC endorsement guides, FDA-OPDP (pharma —
    not used by our 3 industries today, kept for extensibility), TCPA.
  - UK: FCA Consumer Duty, ICO data protection.

This is the **starter** registry. The compliance_checker agent can pull
additional context from chunks at runtime, but having a stable seed list
lets us filter & sort policies by `applicable_industries`/`country`/`state`
without a network call."""

from __future__ import annotations

from bizpulse.models.compliance import PolicyRef


# --- india: central / sectoral regulators -----------------------------------

_RBI_DIGITAL_LENDING = PolicyRef(
    slug="rbi-digital-lending-2022",
    body="RBI",
    title="Digital Lending Guidelines",
    country="IN",
    state=None,
    applicable_industries=["fintech"],
    severity="violation",
    last_updated="2022-09",
    reference_url="https://www.rbi.org.in/Scripts/NotificationUser.aspx?Id=12382",
    summary=(
        "All digital lending must flow through regulated entities; "
        "transparent disclosure of APR, fees, and recovery practices is mandatory. "
        "First-loss default guarantees are restricted."
    ),
    prohibitions=[
        "Marketing 'guaranteed approval' for loans",
        "Concealing the lending entity's identity (REs only)",
        "Hiding APR, fees, or recovery agent details",
    ],
    required_disclosures=[
        "Lending entity name + RBI license/RBI-authorized status",
        "All-in APR (interest + fees), in INR",
        "Recovery practice link",
    ],
    indicative_penalty="License action under Banking Regulation Act / Payment and Settlement Systems Act",
)

_RBI_KYC = PolicyRef(
    slug="rbi-kyc-master-direction",
    body="RBI",
    title="KYC Master Direction (updated periodically)",
    country="IN",
    applicable_industries=["fintech"],
    severity="warning",
    last_updated="2024-01",
    reference_url="https://www.rbi.org.in/Scripts/BS_ViewMasDirections.aspx?id=11566",
    summary=(
        "KYC types (full, min, video) and re-KYC cadence; PEP / sanctions screening; "
        "AML reporting under PMLA."
    ),
    prohibitions=[
        "Marketing accounts as 'no KYC' or 'instant zero-document'",
    ],
    required_disclosures=[
        "KYC tier offered (full / min / video)",
        "Information collected and retention period (per DPDP)",
    ],
)

_SEBI_INVESTOR_ADS = PolicyRef(
    slug="sebi-investor-ads",
    body="SEBI",
    title="Advertisement Code for Investment Advisers / Mutual Funds",
    country="IN",
    applicable_industries=["fintech"],
    severity="violation",
    last_updated="2023-04",
    reference_url="https://www.sebi.gov.in/legal/circulars/apr-2023/advertisement-code-for-investment-advisers-and-research-analysts_70181.html",
    summary=(
        "Past performance disclosure standards; ban on guaranteed-return language; "
        "mandatory risk disclaimers; influencer disclosures."
    ),
    prohibitions=[
        "'Guaranteed returns' or assured-yield language",
        "Selective past-performance display without standardized periods",
        "Hiding risk disclaimers in fine print",
    ],
    required_disclosures=[
        "'Mutual fund investments are subject to market risks' on every ad",
        "Standard 1Y / 3Y / 5Y annualized returns where past performance is shown",
        "SEBI registration number for advisers / research analysts",
    ],
    indicative_penalty="Up to ₹1 crore + suspension of registration",
)

_IRDAI_INSURANCE_ADS = PolicyRef(
    slug="irdai-ads-2024",
    body="IRDAI",
    title="Insurance Advertisements & Disclosure Regulations",
    country="IN",
    applicable_industries=["fintech"],
    severity="violation",
    last_updated="2024-03",
    reference_url="https://www.irdai.gov.in/",
    summary=(
        "Insurance product ads must show insurer registration, sum assured caveats, "
        "and lock-in / surrender details. Comparison ads require written consent of compared insurer."
    ),
    prohibitions=[
        "'No-questions-asked' health-insurance claims",
        "Obscuring waiting periods or pre-existing-disease exclusions",
    ],
    required_disclosures=[
        "IRDAI registration number",
        "Standard policy wording reference",
    ],
)

_DPDP_2023 = PolicyRef(
    slug="dpdp-act-2023",
    body="MeitY",
    title="Digital Personal Data Protection Act",
    country="IN",
    applicable_industries=["fintech", "real_estate", "construction_materials"],
    severity="critical",
    last_updated="2023-08",
    reference_url="https://www.meity.gov.in/data-protection-framework",
    summary=(
        "Consent must be free, specific, informed, unconditional, and unambiguous. "
        "Notice in plain language. Right to correction / erasure. Cross-border data transfer restrictions."
    ),
    prohibitions=[
        "Pre-ticked consent boxes",
        "Bundled consent ('agree to everything' single tick)",
        "Marketing to children without verifiable parental consent",
    ],
    required_disclosures=[
        "Purpose of processing in plain language",
        "Categories of data fiduciaries shared with",
        "How to withdraw consent / file grievance",
    ],
    indicative_penalty="Up to ₹250 crore per instance for significant breaches",
)

_CPA_MISLEADING_ADS = PolicyRef(
    slug="cpa-misleading-ads-2019",
    body="CCPA (Central Consumer Protection Authority)",
    title="Consumer Protection Act — Misleading Advertisements (incl. CCPA Guidelines 2022)",
    country="IN",
    applicable_industries=["fintech", "real_estate", "construction_materials"],
    severity="violation",
    last_updated="2022-06",
    reference_url="https://consumeraffairs.nic.in/",
    summary=(
        "Misleading advertisements (false representation, surrogate ads, bait ads) "
        "attract penalties. Endorsers liable for due diligence on claims."
    ),
    prohibitions=[
        "Surrogate advertising (advertising prohibited goods via lookalike products)",
        "'Bait' ads: low headline price not actually available at scale",
        "Unverifiable superlatives ('best', '#1') without substantiation",
    ],
    required_disclosures=[
        "Material conditions for any 'free' / 'discounted' offer",
        "Disclaimer where 'results may vary'",
    ],
    indicative_penalty="Up to ₹10 lakh first violation; ₹50 lakh subsequent; 2-5 years jail in extreme cases",
)

_GST_MARKETING = PolicyRef(
    slug="gst-marketing-itc",
    body="GST Council",
    title="GST treatment of marketing & advertising spend",
    country="IN",
    applicable_industries=["fintech", "real_estate", "construction_materials"],
    severity="advisory",
    last_updated="2024-06",
    reference_url="https://www.gst.gov.in/",
    summary="Input tax credit on marketing services has industry-specific eligibility; gifts above ₹50K/year to a single recipient need invoicing.",
    required_disclosures=[
        "GSTIN on invoices for marketing services > ₹50,000",
    ],
)

_ASCI_CODE = PolicyRef(
    slug="asci-code",
    body="ASCI",
    title="Advertising Standards Council of India — Code for Self-Regulation",
    country="IN",
    applicable_industries=["fintech", "real_estate", "construction_materials"],
    severity="warning",
    last_updated="2024-02",
    reference_url="https://www.ascionline.in/",
    summary="Self-regulatory code; non-compliance triggers takedown recommendations to MIB and platforms; influencer disclosures (#ad / #sponsored) mandatory.",
    prohibitions=[
        "Influencer posts without #ad / #sponsored / #partnership disclosure",
        "Comparative ads disparaging a named competitor without substantiation",
    ],
    required_disclosures=["Material connection between advertiser and any endorser"],
)

_TRAI_TCCCPR = PolicyRef(
    slug="trai-tccccpr-2018",
    body="TRAI",
    title="Telecom Commercial Communications Customer Preference Regulations",
    country="IN",
    applicable_industries=["fintech", "real_estate", "construction_materials"],
    severity="warning",
    last_updated="2018-07",
    reference_url="https://www.trai.gov.in/",
    summary="Promotional SMS / calls require sender registration on DLT, content templates pre-approved, customer preference (DND) honored.",
    prohibitions=[
        "Promotional SMS to DND-registered numbers",
        "Sending without DLT-registered sender ID / template",
    ],
)

_FEMA_NRI = PolicyRef(
    slug="fema-nri-investments",
    body="RBI / FEMA",
    title="FEMA — NRI investments (Schedule III/IV)",
    country="IN",
    applicable_industries=["real_estate", "fintech"],
    severity="warning",
    last_updated="2023-12",
    reference_url="https://www.rbi.org.in/Scripts/Fema.aspx",
    summary="NRI repatriation limits, restricted property classes (agricultural land, plantations), inward remittance disclosures.",
    prohibitions=[
        "Marketing agricultural / farmhouse / plantation land to NRIs",
        "Implying tax-free repatriation without caveats",
    ],
)

# --- india: state-wise RERA -----------------------------------------------

_RERA_MAHARASHTRA = PolicyRef(
    slug="rera-maharashtra",
    body="MahaRERA",
    title="Maharashtra Real Estate Regulatory Authority",
    country="IN",
    state="maharashtra",
    applicable_industries=["real_estate"],
    severity="violation",
    last_updated="2024-01",
    reference_url="https://maharera.maharashtra.gov.in/",
    summary="MahaRERA registration mandatory for projects >500 sqm or >8 units. Registration number must appear in every ad.",
    prohibitions=[
        "Advertising any project without quoting MahaRERA registration number",
        "Promising possession dates not in the RERA filing",
    ],
    required_disclosures=["MahaRERA registration: P5170...XXXXX (project number)"],
    indicative_penalty="Up to 5% of project cost + 3 years imprisonment for repeated violations",
)

_RERA_KARNATAKA = PolicyRef(
    slug="rera-karnataka",
    body="K-RERA",
    title="Karnataka Real Estate Regulatory Authority",
    country="IN",
    state="karnataka",
    applicable_industries=["real_estate"],
    severity="violation",
    last_updated="2023-11",
    reference_url="https://rera.karnataka.gov.in/",
    summary="K-RERA registration mandatory; same disclosure requirements as central RERA Act.",
    prohibitions=["Advertising without K-RERA registration number"],
    required_disclosures=["K-RERA registration: PRM/KA/RERA/.../XXXXX"],
)

_RERA_TAMILNADU = PolicyRef(
    slug="rera-tamilnadu",
    body="TNRERA",
    title="Tamil Nadu Real Estate Regulatory Authority",
    country="IN",
    state="tamil_nadu",
    applicable_industries=["real_estate"],
    severity="violation",
    last_updated="2023-09",
    reference_url="https://rera.tn.gov.in/",
    summary="TNRERA registration; quarterly project updates mandatory.",
    prohibitions=["Advertising unregistered projects"],
    required_disclosures=["TNRERA registration number on all promotional material"],
)

_RERA_DELHI = PolicyRef(
    slug="rera-delhi",
    body="DDA-RERA",
    title="Delhi Real Estate Regulatory Authority",
    country="IN",
    state="delhi",
    applicable_industries=["real_estate"],
    severity="violation",
    last_updated="2023-04",
    reference_url="https://rera.delhi.gov.in/",
    summary="Delhi RERA registration; advertising without it is a primary violation.",
    prohibitions=["Advertising without Delhi RERA registration number"],
    required_disclosures=["DLRERA registration"],
)

_RERA_UP = PolicyRef(
    slug="rera-uttar-pradesh",
    body="UP-RERA",
    title="Uttar Pradesh Real Estate Regulatory Authority",
    country="IN",
    state="uttar_pradesh",
    applicable_industries=["real_estate"],
    severity="violation",
    last_updated="2023-08",
    reference_url="https://www.up-rera.in/",
    summary="UP-RERA registration; updates on construction milestones every quarter.",
    prohibitions=["Advertising any project without UP-RERA registration"],
    required_disclosures=["UPRERAPRJ#####"],
)

# --- india: industry-specific (construction materials etc.) ---------------

_BIS_IS_CODES = PolicyRef(
    slug="bis-is-codes",
    body="BIS",
    title="Bureau of Indian Standards — IS codes per material category",
    country="IN",
    applicable_industries=["construction_materials"],
    severity="warning",
    last_updated="2024-04",
    reference_url="https://www.bis.gov.in/",
    summary=(
        "Marketing technical claims (compressive strength, anti-bacterial coatings, "
        "fire ratings) must reference the relevant IS code; ISI mark on packaging."
    ),
    prohibitions=[
        "Performance claims without referencing IS code or independent test report",
    ],
    required_disclosures=["Applicable IS code (e.g., IS 269 for OPC cement)"],
)

_GRIHA = PolicyRef(
    slug="griha-rating",
    body="GRIHA Council",
    title="Green Rating for Integrated Habitat Assessment",
    country="IN",
    applicable_industries=["real_estate", "construction_materials"],
    severity="advisory",
    last_updated="2024-06",
    reference_url="https://www.grihaindia.org/",
    summary="Voluntary green-building rating; marketing 'GRIHA-rated' or 'GRIHA-compliant' requires actual certification.",
    prohibitions=["Claiming GRIHA rating without certification"],
    required_disclosures=["GRIHA rating tier (e.g., GRIHA 5-star)"],
)

_IGBC = PolicyRef(
    slug="igbc-certification",
    body="IGBC (CII)",
    title="Indian Green Building Council certifications",
    country="IN",
    applicable_industries=["real_estate", "construction_materials"],
    severity="advisory",
    last_updated="2024-06",
    reference_url="https://igbc.in/",
    summary="Voluntary green certifications. Trademark misuse triggers IGBC takedown.",
    prohibitions=["Using IGBC marks without certification"],
)

# --- EU --------------------------------------------------------------------

_GDPR = PolicyRef(
    slug="eu-gdpr",
    body="EU",
    title="General Data Protection Regulation",
    country="EU",
    applicable_industries=["fintech", "real_estate", "construction_materials"],
    severity="critical",
    last_updated="2018-05",
    reference_url="https://gdpr-info.eu/",
    summary="Lawful basis required for every processing activity; granular consent; right to erasure; 72-hour breach notification.",
    prohibitions=[
        "Pre-ticked consent boxes",
        "Marketing to EU residents without lawful basis",
    ],
    required_disclosures=["Privacy policy with all 13 GDPR-mandated items"],
    indicative_penalty="Up to €20M or 4% of global annual turnover",
)

_EU_AI_ACT = PolicyRef(
    slug="eu-ai-act",
    body="EU",
    title="EU AI Act",
    country="EU",
    applicable_industries=["fintech", "real_estate", "construction_materials"],
    severity="warning",
    last_updated="2024-08",
    reference_url="https://artificialintelligenceact.eu/",
    summary="Risk-based obligations on AI systems; transparency requirements for users interacting with AI; ban on certain manipulative practices.",
    prohibitions=["Subliminal techniques exploiting vulnerabilities"],
    required_disclosures=["User notice when interacting with an AI system or chatbot"],
)

_EU_DSA = PolicyRef(
    slug="eu-dsa",
    body="EU",
    title="Digital Services Act",
    country="EU",
    applicable_industries=["fintech", "real_estate", "construction_materials"],
    severity="warning",
    last_updated="2024-02",
    reference_url="https://digital-strategy.ec.europa.eu/en/policies/digital-services-act-package",
    summary="Transparency on online ads, recommender systems, content moderation. Targets large platforms primarily.",
    prohibitions=["Targeting minors with profiled advertising"],
    required_disclosures=["Why you are seeing this ad"],
)

_EU_MIFID2 = PolicyRef(
    slug="eu-mifid2",
    body="EU",
    title="MiFID II — investment-services marketing",
    country="EU",
    applicable_industries=["fintech"],
    severity="violation",
    last_updated="2018-01",
    reference_url="https://www.esma.europa.eu/policy-rules/mifid-ii-and-mifir",
    summary="Suitability assessment, target-market definition, costs and charges disclosure for any investment marketing.",
    prohibitions=["Marketing complex products without target-market alignment"],
    required_disclosures=["Costs & charges aggregate", "Target market"],
)

# --- US -------------------------------------------------------------------

_FTC_ENDORSEMENTS = PolicyRef(
    slug="us-ftc-endorsements",
    body="FTC",
    title="FTC Endorsement Guides",
    country="US",
    applicable_industries=["fintech", "real_estate", "construction_materials"],
    severity="warning",
    last_updated="2023-06",
    reference_url="https://www.ftc.gov/business-guidance/resources/ftcs-endorsement-guides-what-people-are-asking",
    summary="Endorser must disclose material connection; testimonials must reflect typical results; 'free' offers require accurate cost disclosure.",
    prohibitions=["Hidden material connections with endorsers"],
    required_disclosures=["#ad or 'paid partnership' on endorsement content"],
)

_US_TCPA = PolicyRef(
    slug="us-tcpa",
    body="FCC",
    title="Telephone Consumer Protection Act",
    country="US",
    applicable_industries=["fintech", "real_estate", "construction_materials"],
    severity="violation",
    last_updated="2024-01",
    reference_url="https://www.fcc.gov/document/protecting-consumers-unwanted-robocalls",
    summary="Express written consent for marketing calls / texts; do-not-call registry compliance.",
    prohibitions=["Marketing SMS / calls without express written consent"],
    indicative_penalty="$500–$1,500 per call/text",
)

_US_SEC_ADV = PolicyRef(
    slug="us-sec-advertising-rule",
    body="SEC",
    title="SEC Investment Adviser Marketing Rule",
    country="US",
    applicable_industries=["fintech"],
    severity="violation",
    last_updated="2022-11",
    reference_url="https://www.sec.gov/investment/marketing-faq",
    summary="Advisers must follow specific rules for testimonials, performance, and third-party ratings.",
    prohibitions=["Cherry-picked performance without standardized periods"],
    required_disclosures=["Net-of-fees performance"],
)

# --- UK -------------------------------------------------------------------

_FCA_CONSUMER_DUTY = PolicyRef(
    slug="fca-consumer-duty",
    body="FCA",
    title="FCA Consumer Duty",
    country="GB",
    applicable_industries=["fintech"],
    severity="violation",
    last_updated="2023-07",
    reference_url="https://www.fca.org.uk/firms/consumer-duty",
    summary="Firms must deliver good outcomes for retail customers across products, price/value, understanding, and support.",
    prohibitions=["Marketing claims that obscure key terms or fees"],
    required_disclosures=["Fair value assessment summary on request"],
)

_UK_ICO_DP = PolicyRef(
    slug="uk-ico-dp",
    body="ICO",
    title="UK GDPR / Data Protection Act 2018",
    country="GB",
    applicable_industries=["fintech", "real_estate", "construction_materials"],
    severity="critical",
    last_updated="2024-01",
    reference_url="https://ico.org.uk/",
    summary="UK equivalent of GDPR; same headline rights and breach notification.",
    prohibitions=["Pre-ticked consent boxes"],
    required_disclosures=["Privacy notice with all UK GDPR articles"],
)


# ----- registry -----------------------------------------------------------

_ALL: list[PolicyRef] = [
    # India central
    _RBI_DIGITAL_LENDING, _RBI_KYC, _SEBI_INVESTOR_ADS, _IRDAI_INSURANCE_ADS,
    _DPDP_2023, _CPA_MISLEADING_ADS, _GST_MARKETING, _ASCI_CODE,
    _TRAI_TCCCPR, _FEMA_NRI,
    # India state
    _RERA_MAHARASHTRA, _RERA_KARNATAKA, _RERA_TAMILNADU, _RERA_DELHI, _RERA_UP,
    # India sector
    _BIS_IS_CODES, _GRIHA, _IGBC,
    # EU
    _GDPR, _EU_AI_ACT, _EU_DSA, _EU_MIFID2,
    # US
    _FTC_ENDORSEMENTS, _US_TCPA, _US_SEC_ADV,
    # UK
    _FCA_CONSUMER_DUTY, _UK_ICO_DP,
]

POLICIES: dict[str, PolicyRef] = {p.slug: p for p in _ALL}


def list_policies() -> list[PolicyRef]:
    return list(POLICIES.values())


def applicable(
    *,
    industry: str,
    country: str = "IN",
    state: str | None = None,
) -> list[PolicyRef]:
    """Return policies that apply to (industry, country, state) combination.

    State-specific policies are returned only when `state` matches; if `state`
    is None, only national-level policies are returned. Country='IN' includes
    pan-India regulations and the supplied state's policies."""
    out: list[PolicyRef] = []
    for p in POLICIES.values():
        if p.country != country:
            continue
        if p.applicable_industries and industry not in p.applicable_industries:
            continue
        if p.state is not None and p.state != state:
            continue
        out.append(p)
    return out


def supported_countries() -> set[str]:
    return {p.country for p in POLICIES.values()}


def supported_states(country: str = "IN") -> set[str]:
    return {p.state for p in POLICIES.values() if p.country == country and p.state}
