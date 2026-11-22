"""Curated, Apple-schema-verified catalog for iOS, iPadOS, and watchOS 26/27."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Optional

from ios_debloat.models import CatalogStats, Item, Section

MENU_SECTION = "Menu"
DNS_SECTION = "Encrypted DNS Telemetry & Ad Blocker (unsupervised, iOS/iPadOS 14+)"
STOCK_APPS_SECTION = "Removable Stock Apple Apps (optional USB/Wi-Fi cleanup)"
WATCH_CHECKLIST_SECTION = "watchOS Companion Checklist (manual Watch / iPhone Watch app)"

BUILTIN_PRESETS = ("telemetry", "balanced")
VALID_TARGETS = ("ios", "ipados", "watchos", "all")

APPLE_TELEMETRY_DOMAINS: tuple[str, ...] = (
    "metrics.apple.com",
    "metrics.icloud.com",
    "xp.apple.com",
    "ads.apple.com",
    "advertising.apple.com",
    "api-adservices.apple.com",
    "iadsdk.apple.com",
    "*.iadsdk.apple.com",
    "iadctest.qwapi.com",
    "radarsubmissions.apple.com",
    "idiagnostics.apple.com",
    "iphonesubmissions.apple.com",
    "acfeedbackws.icloud.com",
    "feedbackws.icloud.com",
    "books-analytics-events.apple.com",
    "news-analytics-events.apple.com",
    "stocks-analytics-events.apple.com",
    "weather-analytics-events.apple.com",
    "notes-analytics-events.apple.com",
    "camfx-analytics-events.apple.com",
    "axm-telemetry.apple.com",
    "smoot.apple.com",
    "*.smoot.apple.com",
)

# Strictly curated removable, App-Store-reinstallable Apple built-in apps.
# Core SSV system apps (Settings, Phone, Messages, Safari, Photos, Camera, App Store)
# are NEVER in this set.
REMOVABLE_STOCK_APPS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("com.apple.tips", "Tips app — background tips daemon and notifications (reinstallable from App Store).", ("balanced",)),
    ("com.apple.stocks", "Stocks app — Yahoo Finance background refresh and widgets.", ("balanced",)),
    ("com.apple.news", "Apple News app — newsd background preloading and tracking.", ("balanced",)),
    ("com.apple.tv", "Apple TV app — media suggestions and promotional notifications.", ("balanced",)),
    ("com.apple.podcasts", "Podcasts app — background episode sync and analytics.", ("balanced",)),
    ("com.apple.iBooks", "Apple Books app — bookstore suggestions and iCloud sync.", ("balanced",)),
    ("com.apple.freeform", "Freeform app — collaborative whiteboard and iCloud sync.", ("balanced",)),
    ("com.apple.journal", "Journal app — journaling suggestions engine (JournalingSuggestions).", ("balanced",)),
    ("com.apple.measure", "Measure app — AR measuring utility.", ("balanced",)),
    ("com.apple.compass", "Compass app — standalone compass UI (Maps compass still works).", ("balanced",)),
    ("com.apple.Home", "Apple Home app — HomeKit app UI (optional if you don't use HomeKit).", ("balanced",)),
    ("com.apple.Translate", "Translate app — Apple translation UI (keep if you use Safari/system translate).", ()),
    ("com.apple.VoiceMemos", "Voice Memos app — audio recorder.", ()),
    ("com.apple.weather", "Weather app — location weather widgets and background updates.", ()),
    ("com.apple.Fitness", "Fitness app — Activity/Fitness+ UI (keep if paired with Apple Watch).", ()),
    ("com.apple.Music", "Apple Music app — streaming client and media recommendations.", ()),
    ("com.apple.Maps", "Apple Maps app — navigation and location history.", ()),
    ("com.apple.mobilemail", "Apple Mail app — background mail fetch (remove only if using another client).", ()),
    ("com.apple.shortcuts", "Shortcuts app — automation runner (keep if using custom shortcuts).", ()),
    ("com.apple.Magnifier", "Magnifier app — camera accessibility magnifier.", ()),
)

REMOVABLE_STOCK_APP_IDS: frozenset[str] = frozenset(b for b, _, _ in REMOVABLE_STOCK_APPS)

# Non-essential noisy built-in apps silenced when --silence-notifications is enabled (supervised).
SILENCE_NOTIFICATION_BUNDLES: tuple[str, ...] = (
    "com.apple.tips",
    "com.apple.news",
    "com.apple.stocks",
    "com.apple.tv",
    "com.apple.podcasts",
    "com.apple.journal",
)

# Real iOS/iPadOS background daemons inspected during read-only `debloat --audit`.
TELEMETRY_DAEMONS: dict[str, tuple[str, str]] = {
    "analyticsd": ("telemetry", "Core system analytics aggregation daemon"),
    "diagnosticd": ("telemetry", "System diagnostic log collector"),
    "osanalyticshelper": ("telemetry", "OS analytics submission helper"),
    "SubmitDiagInfo": ("telemetry", "Diagnostic & crash report uploader to Apple"),
    "adprivacyd": ("ads", "Apple Ad Privacy / SKAdNetwork attribution daemon"),
    "promotedcontentd": ("ads", "Apple Search Ads / News / Stocks promoted content daemon"),
    "assistantd": ("siri", "Core Siri voice assistant daemon"),
    "siriknowledged": ("siri", "Siri knowledge graph daemon"),
    "siriinferenced": ("siri", "On-device Siri inference daemon"),
    "sirittsd": ("siri", "Siri text-to-speech daemon"),
    "parsecd": ("siri", "Siri Suggestions & Spotlight internet search backend"),
    "duetexpertd": ("intelligence", "CoreDuet proactive suggestions & usage prediction"),
    "contextstored": ("intelligence", "CoreDuet behavioral context store"),
    "suggestd": ("intelligence", "Proactive Siri Suggestions extraction (Mail/Messages)"),
    "BiomeAgent": ("telemetry", "Biome behavioral event stream agent"),
    "triald": ("telemetry", "Apple Trial A/B experiment & asset rollout daemon"),
    "UsageTrackingAgent": ("telemetry", "App & Screen Time usage tracking agent"),
    "modelcatalogd": ("apple-intelligence", "Apple Intelligence model catalog daemon"),
    "modelmanagerd": ("apple-intelligence", "Apple Intelligence model download & lifecycle"),
    "intelligenceplatformd": ("apple-intelligence", "Apple Intelligence semantic index platform"),
    "intelligencecontextd": ("apple-intelligence", "Apple Intelligence context runtime"),
    "privatecloudcomputed": ("apple-intelligence", "Private Cloud Compute AI offload daemon"),
    "generativeexperiencesd": ("apple-intelligence", "Writing Tools & generative AI daemon"),
    "OTAd": ("updates", "Over-the-air OS update daemon"),
    "mobileassetd": ("assets", "Background system asset & ML/voice download daemon"),
    "routined": ("location", "Significant Locations behavioral tracking daemon"),
    "tipsd": ("bloat", "Apple Tips background daemon"),
    "gamed": ("bloat", "Game Center daemon"),
    "newsd": ("bloat", "Apple News background prefetch daemon"),
    "amsengagementd": ("telemetry", "Apple Media Services engagement & telemetry"),
    "spotlightknowledged": ("intelligence", "CoreSpotlight semantic search indexer"),
    "itunesstored": ("commerce", "iTunes / App Store background store daemon"),
}

DNS_PRESETS: tuple[tuple[str, str, str, Optional[dict[str, object]]], ...] = (
    (
        "dns:none",
        "dns:none",
        "System default DNS (removes any DNS blocker payload).",
        None,
    ),
    (
        "dns:adguard",
        "dns:adguard",
        "AdGuard DNS DoH — blocks Apple ads, trackers, and analytics domains.",
        {
            "protocol": "HTTPS",
            "url": "https://dns.adguard-dns.com/dns-query",
            "addresses": ["94.140.14.14", "94.140.15.15", "2a10:50c0::ad1:ff", "2a10:50c0::ad2:ff"],
        },
    ),
    (
        "dns:mullvad-base",
        "dns:mullvad-base",
        "Mullvad Base DoH — no-logging resolver blocking ads, trackers, and malware.",
        {
            "protocol": "HTTPS",
            "url": "https://base.dns.mullvad.net/dns-query",
            "addresses": ["194.242.2.4", "2a07:e340::4"],
        },
    ),
    (
        "dns:mullvad-all",
        "dns:mullvad-all",
        "Mullvad All DoH — aggressive ad, tracker, telemetry, and social blocking.",
        {
            "protocol": "HTTPS",
            "url": "https://all.dns.mullvad.net/dns-query",
            "addresses": ["194.242.2.9", "2a07:e340::9"],
        },
    ),
    (
        "dns:quad9",
        "dns:quad9",
        "Quad9 DoH — privacy-respecting DNS with malware/phishing threat blocking.",
        {
            "protocol": "HTTPS",
            "url": "https://dns.quad9.net/dns-query",
            "addresses": ["9.9.9.9", "149.112.112.112", "2620:fe::fe", "2620:fe::9"],
        },
    ),
    (
        "dns:controld",
        "dns:controld",
        "Control D Free DoH — blocks ads, trackers, and telemetry endpoints.",
        {
            "protocol": "HTTPS",
            "url": "https://freedns.controld.com/p2",
            "addresses": ["76.76.2.11", "76.76.10.11"],
        },
    ),
    (
        "dns:nextdns",
        "dns:nextdns",
        "NextDNS DoH — uses your NextDNS profile ID (--dns nextdns:<id> or prompt).",
        {
            "protocol": "HTTPS",
            "url": "https://dns.nextdns.io/{id}",
            "addresses": [],
        },
    ),
)

WATCH_CHECKLIST: tuple[tuple[str, str, str], ...] = (
    (
        "watch:bg-refresh",
        "watch:bg-refresh",
        "Watch app -> General -> Background App Refresh -> Off (or per-app). Saves battery & network wakeups.",
    ),
    (
        "watch:auto-app-install",
        "watch:auto-app-install",
        "Watch app -> General -> Automatic App Install -> Off. Prevents iPhone apps auto-installing Watch bloat.",
    ),
    (
        "watch:analytics",
        "watch:analytics",
        "Watch app -> Privacy -> Analytics & Improvements -> Share Watch Analytics Off.",
    ),
    (
        "watch:siri-listen",
        "watch:siri-listen",
        "Watch app -> Siri -> turn off Listen for Siri and Raise to Speak (stops continuous mic wakeups).",
    ),
    (
        "watch:siri-analytics",
        "watch:siri-analytics",
        "iPhone Settings -> Privacy & Security -> Analytics & Improvements -> Improve Siri & Dictation Off.",
    ),
    (
        "watch:live-activities",
        "watch:live-activities",
        "Watch app -> Smart Stack -> Live Activities -> disable Auto-Launch & background media apps.",
    ),
    (
        "watch:handoff",
        "watch:handoff",
        "Watch app -> General -> Enable Handoff -> Off (unless you use Watch->Mac/iPhone continuity).",
    ),
    (
        "watch:always-on",
        "watch:always-on",
        "Watch app -> Display & Brightness -> Always On -> Off (major battery & wake reduction).",
    ),
    (
        "watch:noise",
        "watch:noise",
        "Watch app -> Noise -> Environmental Sound Measurements -> Off (stops periodic background mic sampling).",
    ),
    (
        "watch:walkie-talkie",
        "watch:walkie-talkie",
        "On Apple Watch Home Screen -> remove unused stock apps (Walkie-Talkie, Stocks, News, Tips, Mindfulness).",
    ),
)

# Each restriction entry:
# (section, payload_key, debloat_value, supervised, platforms, presets, deprecated_in, ddm_spec, comment)
_RESTRICTIONS: tuple[
    tuple[
        str,
        str,
        bool,
        bool,
        tuple[str, ...],
        tuple[str, ...],
        Optional[str],
        Optional[tuple[str, tuple[str, ...], bool]],
        str,
    ],
    ...,
] = (
    # === Telemetry, Diagnostics & Apple Ads ===
    (
        "Telemetry, Diagnostics & Apple Ads",
        "allowDiagnosticSubmission",
        False,
        False,
        ("ios", "ipados"),
        ("telemetry", "balanced"),
        None,
        None,
        "Stop automatic diagnostic, usage, and crash telemetry submission to Apple.",
    ),
    (
        "Telemetry, Diagnostics & Apple Ads",
        "allowApplePersonalizedAdvertising",
        False,
        False,
        ("ios", "ipados"),
        ("telemetry", "balanced"),
        None,
        None,
        "Disable Apple Personalized Ads in App Store, Apple News, and Stocks.",
    ),
    (
        "Telemetry, Diagnostics & Apple Ads",
        "forceLimitAdTracking",
        True,
        False,
        ("ios", "ipados"),
        ("telemetry", "balanced"),
        None,
        None,
        "Enforce Limit Ad Tracking system-wide across apps.",
    ),
    (
        "Telemetry, Diagnostics & Apple Ads",
        "allowDiagnosticSubmissionModification",
        False,
        True,
        ("ios", "ipados"),
        ("telemetry", "balanced"),
        None,
        None,
        "Lock diagnostic sharing off so OS updates cannot re-enable Share Analytics.",
    ),
    # === Siri & Spotlight Suggestions ===
    (
        "Siri & Spotlight Suggestions",
        "allowSpotlightInternetResults",
        False,
        False,
        ("ios", "ipados"),
        ("telemetry", "balanced"),
        None,
        None,
        "Disable Siri Suggestions & Spotlight web/cloud lookups (smoot.apple.com). Local Spotlight search stays fast.",
    ),
    (
        "Siri & Spotlight Suggestions",
        "allowAssistant",
        False,
        False,
        ("ios", "ipados"),
        ("balanced",),
        "26.4",
        ("com.apple.configuration.siri.settings", ("Enabled",), False),
        "Disable Siri assistant globally (Siri voice & Hey Siri stop; CarPlay Siri stops).",
    ),
    (
        "Siri & Spotlight Suggestions",
        "allowAssistantWhileLocked",
        False,
        False,
        ("ios", "ipados", "watchos"),
        ("balanced",),
        "26.4",
        ("com.apple.configuration.siri.settings", ("AllowWhileLocked",), False),
        "Disable Siri while device is locked (applies to iPhone, iPad, and paired Apple Watch).",
    ),
    (
        "Siri & Spotlight Suggestions",
        "allowSiriAI",
        False,
        False,
        ("ios", "ipados"),
        ("balanced",),
        "27.0",
        ("com.apple.configuration.siri.settings", ("AllowSiriAI",), False),
        "Disable Apple Intelligence integration inside Siri (iOS/iPadOS 27+).",
    ),
    (
        "Siri & Spotlight Suggestions",
        "allowAssistantUserGeneratedContent",
        False,
        True,
        ("ios", "ipados", "watchos"),
        ("balanced",),
        "26.4",
        ("com.apple.configuration.siri.settings", ("AllowUserGeneratedContent",), False),
        "Stop Siri fetching web/user-generated content (applies to iPhone, iPad, and paired Apple Watch).",
    ),
    # === Apple Intelligence & Cloud AI ===
    (
        "Apple Intelligence & Cloud AI",
        "allowExternalIntelligenceIntegrations",
        False,
        False,
        ("ios", "ipados"),
        ("balanced",),
        "26.4",
        ("com.apple.configuration.external-intelligence.settings", ("Enabled",), False),
        "Disable third-party cloud AI extensions (ChatGPT integration in Siri / Writing Tools).",
    ),
    (
        "Apple Intelligence & Cloud AI",
        "allowExternalIntelligenceIntegrationsSignIn",
        False,
        False,
        ("ios", "ipados"),
        ("balanced",),
        "26.4",
        ("com.apple.configuration.external-intelligence.settings", ("AllowSignIn",), False),
        "Prevent signing into external AI provider accounts inside Apple Intelligence.",
    ),
    (
        "Apple Intelligence & Cloud AI",
        "allowWritingTools",
        False,
        True,
        ("ios", "ipados"),
        ("balanced",),
        "26.4",
        ("com.apple.configuration.intelligence.settings", ("AllowWritingTools",), False),
        "Disable Apple Intelligence Writing Tools (rewrite/proofread/summarize UI).",
    ),
    (
        "Apple Intelligence & Cloud AI",
        "allowGenmoji",
        False,
        True,
        ("ios", "ipados"),
        ("balanced",),
        "26.4",
        ("com.apple.configuration.intelligence.settings", ("AllowGenmoji",), False),
        "Disable Genmoji AI emoji generation in Messages and keyboard.",
    ),
    (
        "Apple Intelligence & Cloud AI",
        "allowImagePlayground",
        False,
        True,
        ("ios", "ipados"),
        ("balanced",),
        "26.4",
        ("com.apple.configuration.intelligence.settings", ("AllowImagePlayground",), False),
        "Disable Image Playground generative image creation.",
    ),
    (
        "Apple Intelligence & Cloud AI",
        "allowImageWand",
        False,
        True,
        ("ios", "ipados"),
        ("balanced",),
        "26.4",
        ("com.apple.configuration.intelligence.settings", ("AllowImageWand",), False),
        "Disable Image Wand AI sketch generation in Apple Notes.",
    ),
    (
        "Apple Intelligence & Cloud AI",
        "allowMailSummary",
        False,
        True,
        ("ios", "ipados"),
        ("balanced",),
        "26.4",
        ("com.apple.configuration.intelligence.settings", ("Apps", "Mail", "AllowSummary"), False),
        "Disable Apple Intelligence email summarization in Mail.",
    ),
    (
        "Apple Intelligence & Cloud AI",
        "allowMailSmartReplies",
        False,
        True,
        ("ios", "ipados"),
        ("balanced",),
        "26.4",
        ("com.apple.configuration.intelligence.settings", ("Apps", "Mail", "AllowSmartReplies"), False),
        "Disable AI-generated Smart Replies in Mail.",
    ),
    (
        "Apple Intelligence & Cloud AI",
        "allowSafariSummary",
        False,
        True,
        ("ios", "ipados"),
        ("balanced",),
        "26.4",
        ("com.apple.configuration.intelligence.settings", ("Apps", "Safari", "AllowSummary"), False),
        "Disable Safari webpage AI summarization.",
    ),
    (
        "Apple Intelligence & Cloud AI",
        "allowNotesTranscription",
        False,
        True,
        ("ios", "ipados"),
        ("balanced",),
        "26.4",
        ("com.apple.configuration.intelligence.settings", ("Apps", "Notes", "AllowTranscription"), False),
        "Disable Notes live audio-to-text transcription.",
    ),
    (
        "Apple Intelligence & Cloud AI",
        "allowNotesTranscriptionSummary",
        False,
        True,
        ("ios", "ipados"),
        ("balanced",),
        "26.4",
        ("com.apple.configuration.intelligence.settings", ("Apps", "Notes", "AllowTranscriptionSummary"), False),
        "Disable Notes AI summaries of recorded audio transcripts.",
    ),
    (
        "Apple Intelligence & Cloud AI",
        "allowVisualIntelligenceSummary",
        False,
        True,
        ("ios", "ipados"),
        ("balanced",),
        "26.4",
        ("com.apple.configuration.intelligence.settings", ("AllowVisualIntelligenceSummary",), False),
        "Disable Visual Intelligence camera object/text AI summaries.",
    ),
    (
        "Apple Intelligence & Cloud AI",
        "allowAppleIntelligenceReport",
        False,
        True,
        ("ios", "ipados"),
        ("telemetry", "balanced"),
        "26.4",
        ("com.apple.configuration.intelligence.settings", ("AllowAppleIntelligenceReport",), False),
        "Disable Apple Intelligence Report privacy/telemetry logging.",
    ),
    (
        "Apple Intelligence & Cloud AI",
        "allowPersonalizedHandwritingResults",
        False,
        True,
        ("ios", "ipados"),
        ("balanced",),
        "26.4",
        ("com.apple.configuration.intelligence.settings", ("AllowPersonalizedHandwritingResults",), False),
        "Disable iPadOS/iOS personalized Apple Pencil handwriting ML adaptation.",
    ),
    # === Keyboard, Dictation & On-Device Processing ===
    (
        "Keyboard, Dictation & On-Device Processing",
        "forceOnDeviceOnlyDictation",
        True,
        False,
        ("ios", "ipados", "watchos"),
        ("telemetry", "balanced"),
        "26.4",
        ("com.apple.configuration.intelligence.settings", ("ForceOnDeviceOnlyDictation",), True),
        "Force dictation strictly on-device (blocks sending voice audio to Apple servers; works on Watch too).",
    ),
    (
        "Keyboard, Dictation & On-Device Processing",
        "forceOnDeviceOnlyTranslation",
        True,
        False,
        ("ios", "ipados", "watchos"),
        ("telemetry", "balanced"),
        "26.4",
        ("com.apple.configuration.intelligence.settings", ("ForceOnDeviceOnlyTranslation",), True),
        "Force Translate requests strictly on-device (works on iPhone, iPad, and Watch).",
    ),
    (
        "Keyboard, Dictation & On-Device Processing",
        "allowDictation",
        False,
        True,
        ("ios", "ipados"),
        ("balanced",),
        "26.4",
        ("com.apple.configuration.keyboard.settings", ("AllowDictation",), False),
        "Disable keyboard microphone dictation completely.",
    ),
    (
        "Keyboard, Dictation & On-Device Processing",
        "allowPredictiveKeyboard",
        False,
        True,
        ("ios", "ipados"),
        (),
        "26.4",
        ("com.apple.configuration.keyboard.settings", ("AllowPredictiveText",), False),
        "Disable predictive QuickType bar and local typing prediction model (opt-in).",
    ),
    (
        "Keyboard, Dictation & On-Device Processing",
        "allowDefinitionLookup",
        False,
        True,
        ("ios", "ipados"),
        ("balanced",),
        "26.4",
        ("com.apple.configuration.keyboard.settings", ("AllowDefinitionLookup",), False),
        "Disable Look Up web/Siri dictionary queries on highlighted text.",
    ),
    (
        "Keyboard, Dictation & On-Device Processing",
        "allowAutoCorrection",
        False,
        True,
        ("ios", "ipados"),
        (),
        "26.4",
        ("com.apple.configuration.keyboard.settings", ("AllowAutoCorrection",), False),
        "Disable keyboard auto-correction (opt-in; off in presets).",
    ),
    (
        "Keyboard, Dictation & On-Device Processing",
        "allowSpellCheck",
        False,
        True,
        ("ios", "ipados"),
        (),
        "26.4",
        ("com.apple.configuration.keyboard.settings", ("AllowSpellCheck",), False),
        "Disable keyboard spell-check underlines (opt-in; off in presets).",
    ),
    # === Continuity, Handoff & Background Sync ===
    (
        "Continuity, Handoff & Background Sync",
        "allowActivityContinuation",
        False,
        False,
        ("ios", "ipados"),
        ("balanced",),
        None,
        None,
        "Disable Handoff background BLE/iCloud activity sharing between Apple devices.",
    ),
    (
        "Continuity, Handoff & Background Sync",
        "allowGlobalBackgroundFetchWhenRoaming",
        False,
        False,
        ("ios", "ipados"),
        ("balanced",),
        None,
        None,
        "Block global background app/data fetch while cellular roaming.",
    ),
    (
        "Continuity, Handoff & Background Sync",
        "allowiPhoneWidgetsOnMac",
        False,
        True,
        ("ios",),
        ("balanced",),
        None,
        None,
        "Stop streaming iPhone widgets over Continuity to macOS Desktop.",
    ),
    (
        "Continuity, Handoff & Background Sync",
        "allowiPhoneMirroring",
        False,
        True,
        ("ios",),
        ("balanced",),
        None,
        None,
        "Disable iPhone Mirroring Continuity connection & notification relay to macOS.",
    ),
    (
        "Continuity, Handoff & Background Sync",
        "allowProximitySetupToNewDevice",
        False,
        True,
        ("ios", "ipados"),
        ("balanced",),
        None,
        None,
        "Stop nearby-device Quick Start BLE proximity popups.",
    ),
    (
        "Continuity, Handoff & Background Sync",
        "allowAirPrintiBeaconDiscovery",
        False,
        True,
        ("ios", "ipados"),
        ("balanced",),
        None,
        None,
        "Stop background iBeacon scanning for AirPrint printers.",
    ),
    (
        "Continuity, Handoff & Background Sync",
        "allowAutomaticAppDownloads",
        False,
        True,
        ("ios", "ipados", "watchos"),
        ("balanced",),
        None,
        None,
        "Stop automatic App Store downloads pushed from other Apple devices or iPhone->Watch.",
    ),
    # === Apple Media, Apps & Cloud Services ===
    (
        "Apple Media, Apps & Cloud Services",
        "allowNews",
        False,
        True,
        ("ios", "ipados"),
        (),
        None,
        None,
        "Disable Apple News app, Today News widget, and background newsd.",
    ),
    (
        "Apple Media, Apps & Cloud Services",
        "allowGameCenter",
        False,
        True,
        ("ios", "ipados"),
        (),
        None,
        None,
        "Disable Game Center & gamed background sign-in prompts.",
    ),
    (
        "Apple Media, Apps & Cloud Services",
        "allowAddingGameCenterFriends",
        False,
        True,
        ("ios", "ipados"),
        (),
        None,
        None,
        "Block Game Center friend invitations.",
    ),
    (
        "Apple Media, Apps & Cloud Services",
        "allowAppClips",
        False,
        True,
        ("ios", "ipados"),
        (),
        None,
        None,
        "Disable App Clips instant-download runtime.",
    ),
    (
        "Apple Media, Apps & Cloud Services",
        "allowPodcasts",
        False,
        True,
        ("ios", "ipados"),
        (),
        None,
        None,
        "Disable Apple Podcasts app and background feed refresh.",
    ),
    (
        "Apple Media, Apps & Cloud Services",
        "allowMusicService",
        False,
        True,
        ("ios", "ipados"),
        (),
        None,
        None,
        "Disable Apple Music streaming & radio tab (local synced music remains).",
    ),
    (
        "Apple Media, Apps & Cloud Services",
        "allowRadioService",
        False,
        True,
        ("ios", "ipados"),
        (),
        None,
        None,
        "Disable Apple Music Radio streaming.",
    ),
    (
        "Apple Media, Apps & Cloud Services",
        "allowBookstore",
        False,
        True,
        ("ios", "ipados"),
        (),
        None,
        None,
        "Disable Apple Books Store tab (local PDFs/EPUBs remain).",
    ),
    (
        "Apple Media, Apps & Cloud Services",
        "allowiTunes",
        False,
        True,
        ("ios", "ipados"),
        (),
        None,
        None,
        "Disable iTunes Store app (App Store stays enabled).",
    ),
    (
        "Apple Media, Apps & Cloud Services",
        "allowLiveVoicemail",
        False,
        True,
        ("ios",),
        (),
        None,
        None,
        "Disable on-device Live Voicemail transcription on iPhone.",
    ),
    (
        "Apple Media, Apps & Cloud Services",
        "allowAirDrop",
        False,
        True,
        ("ios", "ipados"),
        (),
        None,
        None,
        "Disable AirDrop discovery and file transfers.",
    ),
    (
        "Apple Media, Apps & Cloud Services",
        "allowCloudBackup",
        False,
        False,
        ("ios", "ipados"),
        (),
        None,
        None,
        "Disable iCloud Backup (opt-in — use encrypted Mac/PC backups instead).",
    ),
    (
        "Apple Media, Apps & Cloud Services",
        "allowCloudPhotoLibrary",
        False,
        False,
        ("ios", "ipados"),
        (),
        None,
        None,
        "Disable iCloud Photos sync (opt-in — existing cloud-only originals stop syncing).",
    ),
    (
        "Apple Media, Apps & Cloud Services",
        "allowCloudKeychainSync",
        False,
        False,
        ("ios", "ipados"),
        (),
        None,
        None,
        "Disable iCloud Keychain password sync (opt-in — use local/1Password/Bitwarden instead).",
    ),
    (
        "Apple Media, Apps & Cloud Services",
        "allowSharedStream",
        False,
        False,
        ("ios", "ipados"),
        (),
        None,
        None,
        "Disable iCloud Shared Photo Albums.",
    ),
    (
        "Apple Media, Apps & Cloud Services",
        "allowCloudDocumentSync",
        False,
        True,
        ("ios", "ipados"),
        (),
        None,
        None,
        "Disable iCloud Drive document/app-data sync.",
    ),
    (
        "Apple Media, Apps & Cloud Services",
        "allowCloudPrivateRelay",
        False,
        True,
        ("ios", "ipados"),
        (),
        None,
        None,
        "Disable iCloud Private Relay (useful if you already run your own VPN/DoH).",
    ),
    (
        "Apple Media, Apps & Cloud Services",
        "allowLockScreenTodayView",
        False,
        False,
        ("ios", "ipados"),
        (),
        None,
        None,
        "Remove the swipe-right Today widget page from the Lock Screen.",
    ),
    (
        "Apple Media, Apps & Cloud Services",
        "allowSafari",
        False,
        True,
        ("ios", "ipados"),
        (),
        None,
        None,
        "Hide Safari (HIGH RISK — also disables in-app SFSafariViewController web logins; --disable-all only).",
    ),
    (
        "Apple Media, Apps & Cloud Services",
        "allowChat",
        False,
        True,
        ("ios", "ipados"),
        (),
        None,
        None,
        "Disable Messages / iMessage app (HIGH RISK — --disable-all only).",
    ),
)


def build_catalog(target: str = "all", user_labels: Optional[list[Item]] = None) -> list[Section]:
    """Construct the ordered list of Sections and Items for the given target platform."""
    if target not in VALID_TARGETS:
        raise ValueError(f"Unsupported target {target!r}; expected one of {VALID_TARGETS}")

    sections: list[Section] = []

    watch_sec: Optional[Section] = None
    if target in ("all", "watchos"):
        watch_items = [
            Item(
                id=item_id,
                kind="watch_check",
                label=label,
                section=WATCH_CHECKLIST_SECTION,
                comment=comment,
                platforms=("watchos",),
                disabled=False,
                selected=False,
                active=False,
            )
            for item_id, label, comment in WATCH_CHECKLIST
        ]
        watch_sec = Section(title=WATCH_CHECKLIST_SECTION, kind="watch_check", items=watch_items)

    # Place watchOS manual checklist first when targeting watchOS directly
    if target == "watchos" and watch_sec is not None:
        sections.append(watch_sec)

    # 1. DNS Section (not supported on watchOS)
    if target in ("all", "ios", "ipados"):
        dns_items: list[Item] = []
        for item_id, label, comment, dns_cfg in DNS_PRESETS:
            is_none = item_id == "dns:none"
            dns_items.append(
                Item(
                    id=item_id,
                    kind="dns",
                    label=label,
                    section=DNS_SECTION,
                    comment=comment,
                    supervised=False,
                    platforms=("ios", "ipados"),
                    dns_config=deepcopy(dns_cfg),
                    selected=is_none,
                    active=is_none,
                    disabled=False,
                )
            )
        sections.append(Section(title=DNS_SECTION, kind="dns", items=dns_items))

    # 2. Restriction Sections (preserve insertion order)
    by_section: dict[str, Section] = {}
    for sec_title, key, debloat_val, supervised, platforms, presets, dep_in, ddm, comment in _RESTRICTIONS:
        if target != "all" and target not in platforms:
            continue
        sec = by_section.get(sec_title)
        if sec is None:
            sec = Section(title=sec_title, kind="restriction", items=[])
            by_section[sec_title] = sec
            sections.append(sec)
        sec.items.append(
            Item(
                id=key,
                kind="restriction",
                label=key,
                section=sec_title,
                comment=comment,
                presets=presets,
                supervised=supervised,
                platforms=platforms,
                payload_key=key,
                debloat_value=debloat_val,
                ddm_spec=ddm,
                deprecated_in=dep_in,
                disabled=False,
                selected=True,
            )
        )

    # 3. Removable Stock Apps (iOS / iPadOS)
    if target in ("all", "ios", "ipados"):
        app_items = [
            Item(
                id=f"app:{bundle_id}",
                kind="stock_app",
                label=bundle_id,
                section=STOCK_APPS_SECTION,
                comment=comment,
                presets=presets,
                supervised=False,
                platforms=("ios", "ipados"),
                bundle_id=bundle_id,
                disabled=False,
                selected=True,
            )
            for bundle_id, comment, presets in REMOVABLE_STOCK_APPS
        ]
        sections.append(Section(title=STOCK_APPS_SECTION, kind="stock_app", items=app_items))

    # 4. watchOS Checklist (when targeting "all"; already first for "watchos")
    if target == "all" and watch_sec is not None:
        sections.append(watch_sec)

    # 5. Optional custom user items from ~/.ios-debloat/labels.txt
    if user_labels:
        custom_sec = Section(title="User Custom Labels", kind="restriction", items=[])
        for it in user_labels:
            if target == "all" or target in it.platforms:
                it_copy = deepcopy(it)
                it_copy.section = custom_sec.title
                custom_sec.items.append(it_copy)
        if custom_sec.items:
            sections.append(custom_sec)

    return sections


def catalog_stats(sections: Optional[list[Section]] = None) -> CatalogStats:
    """Compute exact catalog statistics from the built catalog."""
    secs = sections if sections is not None else build_catalog("all")
    all_items = [it for sec in secs for it in sec.items]
    restrictions = [it for it in all_items if it.kind == "restriction"]
    unsup = [it for it in restrictions if not it.supervised]
    sup = [it for it in restrictions if it.supervised]
    dns_presets = [it for it in all_items if it.kind == "dns" and it.id != "dns:none"]
    stock_apps = [it for it in all_items if it.kind == "stock_app"]
    watch_checks = [it for it in all_items if it.kind == "watch_check"]
    watch_prof = [it for it in restrictions if "watchos" in it.platforms]
    return CatalogStats(
        sections=len(secs),
        restrictions_total=len(restrictions),
        restrictions_unsupervised=len(unsup),
        restrictions_supervised=len(sup),
        telemetry_preset=sum(1 for it in restrictions if "telemetry" in it.presets),
        balanced_preset=sum(1 for it in restrictions if "balanced" in it.presets),
        dns_presets=len(dns_presets),
        stock_apps=len(stock_apps),
        watch_checklist=len(watch_checks),
        watch_profile_keys=len(watch_prof),
        telemetry_daemons=len(TELEMETRY_DAEMONS),
    )


def parse_preset_lines(text: str) -> set[str]:
    """Parse line-based preset files (`item_id # comment`), matching mac-os-debloat."""
    ids: set[str] = set()
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        # Allow optional inline [supervised] tag at end of line
        token = line.split()[0].strip()
        if token:
            ids.add(token)
    return ids


def resolve_preset(
    sections: list[Section],
    name: str,
    presets_dir: Optional[Path] = None,
) -> Optional[set[str]]:
    """Return the set of item IDs targeted for debloat by `name`, or None if unknown."""
    if name in BUILTIN_PRESETS:
        return {
            it.id
            for sec in sections
            for it in sec.items
            if it.kind == "restriction" and name in it.presets
        }
    if presets_dir is not None:
        candidate = presets_dir / (name if name.endswith(".txt") else f"{name}.txt")
        if candidate.is_file():
            known_ids = {it.id for sec in sections for it in sec.items if it.kind in ("restriction", "stock_app", "dns")}
            return parse_preset_lines(candidate.read_text(encoding="utf-8")) & known_ids
    return None


def format_catalog_list(sections: list[Section]) -> str:
    """Format the catalog in preset file syntax (`--list`), matching mac-os-debloat."""
    lines = [
        "# Format: item_id  # [tags] comment (delete lines you want to keep enabled)",
        "# Lines starting with `# ===` are section headers.",
        "",
    ]
    for sec in sections:
        lines.append(f"# === {sec.title} ===")
        for it in sec.items:
            tags: list[str] = []
            if it.supervised:
                tags.append("supervised")
            if "watchos" in it.platforms:
                tags.append("watchOS")
            for p in it.presets:
                tags.append(p)
            prefix = f"[{', '.join(tags)}] " if tags else ""
            lines.append(f"{it.id:<46} # {prefix}{it.comment}")
        lines.append("")
    return "\n".join(lines)


def export_blocklist(fmt: str = "domains") -> str:
    """Export the safe Apple telemetry & ad domain blocklist in domains, adguard, or hosts format."""
    fmt_low = fmt.lower()
    if fmt_low == "domains":
        header = "# Safe Apple Telemetry & Ad Domains (preserves iCloud, iMessage, APNs, App Store, Updates)\n"
        return header + "\n".join(APPLE_TELEMETRY_DOMAINS) + "\n"
    if fmt_low == "adguard":
        header = "! Title: ios-watchos-ipados-debloat Safe Apple Telemetry Blocklist\n"
        rules = []
        for dom in APPLE_TELEMETRY_DOMAINS:
            clean = dom[2:] if dom.startswith("*.") else dom
            rules.append(f"||{clean}^")
        return header + "\n".join(rules) + "\n"
    if fmt_low == "hosts":
        header = "# Safe Apple Telemetry & Ad Hosts (exact hostnames only; wildcards commented)\n"
        rows = []
        for dom in APPLE_TELEMETRY_DOMAINS:
            if dom.startswith("*."):
                rows.append(f"# wildcard (use DNS/AdGuard filter): {dom}")
            else:
                rows.append(f"0.0.0.0 {dom}")
        return header + "\n".join(rows) + "\n"
    raise ValueError(f"Unsupported blocklist format {fmt!r}; expected domains, adguard, or hosts")
