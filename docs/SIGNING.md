# Code signing (optional)

The app ships **unsigned by default**, which is fine for a soft or internal
launch: users click through a one-time OS warning. When you want a polished
public download, add the secrets below and the CI workflow signs automatically
- no code change needed. Every signing step is gated on its secret, so leaving
them unset simply produces unsigned builds.

## The honest cost picture

| Platform | Removes the warning? | Cost | Notes |
|---|---|---|---|
| Unsigned (default) | No | Free | Windows: "More info -> Run anyway". macOS: right-click -> Open. |
| Self-signed | No | Free | Pointless for distribution - users would have to trust your root cert. |
| **Azure Trusted Signing** | **Yes (Windows, immediately)** | **~$10/mo** | Recommended. Cloud, no hardware token. |
| Traditional OV cert | Eventually (reputation) | ~$200-400/yr | `.pfx` in secrets. Still warns at first. |
| Traditional EV cert | Yes (Windows, immediately) | ~$350-600/yr | Needs hardware token or cloud HSM. |
| Apple Developer Program | Yes (macOS) | $99/yr | Only path for macOS. |

There is **no Google/GCP code-signing option** - Authenticode (Windows) and
Apple signing are rooted in Microsoft's and Apple's programs respectively.

## Enable Windows signing (Azure Trusted Signing)

1. Create an Azure account and a **Trusted Signing** account + a **certificate
   profile**. Complete the one-time identity validation for Vida Solutions, Inc.
   (a few business days; you must be a verifiable legal entity - you are).
2. Create an Entra app registration (service principal) and grant it the
   "Trusted Signing Certificate Profile Signer" role on the account.
3. Add these repo secrets (Settings -> Secrets and variables -> Actions):
   - `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`
   - `AZ_TS_ENDPOINT` (e.g. `https://eus.codesigning.azure.net/`)
   - `AZ_TS_ACCOUNT` (your Trusted Signing account name)
   - `AZ_TS_PROFILE` (your certificate profile name)
4. Re-run the build. Both `IntakeAgent.exe` and `IntakeAgentSetup.exe` get signed
   and timestamped.

## Enable macOS signing + notarization

1. Enroll in the **Apple Developer Program** ($99/yr).
2. Create a **Developer ID Application** certificate; export it as a `.p12`.
3. Create an app-specific password for your Apple ID; note your Team ID.
4. Add these repo secrets:
   - `APPLE_CERT_P12` (base64 of the `.p12`), `APPLE_CERT_PASSWORD`
   - `APPLE_SIGN_IDENTITY` (e.g. `Developer ID Application: Vida Solutions, Inc. (TEAMID)`)
   - `APPLE_ID`, `APPLE_APP_PASSWORD`, `APPLE_TEAM_ID`
5. Re-run the build. The `.app` is codesigned and the `.dmg` is notarized + stapled.

## Linux

AppImages are conventionally unsigned; no action needed. You can optionally
GPG-sign the file and publish the signature alongside it.
