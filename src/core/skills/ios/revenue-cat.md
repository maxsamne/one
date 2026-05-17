> In-app purchases and subscriptions for iOS using RevenueCat — setup, paywalls, entitlements.

# RevenueCat — In-App Purchases & Subscriptions

## Agent hints
- **Output path:** integrate into the existing app at `apps/ios/<AppName>/`
- **Preferred thinking:** coding → `medium`
- **Commonly related skills:** [swiftui.md](swiftui.md)

## Concepts

- **Product:** SKU defined in App Store Connect (consumable, non-consumable, subscription)
- **Entitlement:** access level your app checks (e.g. `"pro"`). Maps to one or more products.
- **Offering:** the set of packages you show on a paywall. Switch offerings remotely without an update.
- **Package:** a product bundled with a duration hint (`monthly`, `annual`, `lifetime`, etc.)
- **CustomerInfo:** the live subscription state for a user. Always fetch from SDK — never cache locally.

---

## Setup

### 1. App Store Connect
Create subscription products under your app → Subscriptions. Note the product IDs.

### 2. RevenueCat dashboard
- Create project → add iOS app → paste App Store Connect shared secret
- Entitlements → create (e.g. `pro`) → attach products
- Offerings → create → add packages pointing to products

### 3. Xcode capability
Target → Signing & Capabilities → + → **In-App Purchase**

### 4. Install SDK (SPM)
```
https://github.com/RevenueCat/purchases-ios-spm.git
```
Select packages: `RevenueCat` + `RevenueCatUI` (for built-in paywalls)

---

## Configure

```swift
import RevenueCat

@main
struct MyApp: App {
    init() {
        Purchases.logLevel = .debug  // remove in production
        Purchases.configure(
            with: Configuration
                .builder(withAPIKey: "appl_xxxx")
                .build()
        )
    }
}
```

Pass `appUserID:` if you have your own auth system; omit for anonymous IDs.

---

## Check subscription status

Stream `CustomerInfo` updates for the lifetime of the app:

```swift
@Observable
final class CustomerState {
    var isPro = false

    func observe() async {
        for await info in Purchases.shared.customerInfoStream {
            isPro = info.entitlements.active["pro"] != nil
        }
    }
}
```

Use `.task { await customerState.observe() }` on your root view.

One-off check (e.g. on a gated screen):

```swift
let info = try await Purchases.shared.customerInfo()
guard info.entitlements.active["pro"] != nil else { /* show paywall */ }
```

---

## Fetch offerings

```swift
let offerings = try await Purchases.shared.offerings()
let current = offerings.current          // your default offering
let packages = current?.availablePackages
```

---

## Make a purchase

```swift
let (_, customerInfo, _) = try await Purchases.shared.purchase(package: package)
if customerInfo.entitlements.active["pro"] != nil {
    // unlock
}
```

---

## Built-in paywall (RevenueCatUI)

Simplest — uses your paywall template from the dashboard:

```swift
.sheet(isPresented: $showPaywall) {
    PaywallView()
}
```

Auto-present based on entitlement:

```swift
.presentPaywallIfNeeded(requiredEntitlementIdentifier: "pro") { customerInfo in
    // called after purchase or restore
}

// or custom condition
.presentPaywallIfNeeded { customerInfo in
    customerInfo.entitlements.active["pro"] == nil
} purchaseCompleted: { info in ... }
  restoreCompleted: { info in ... }
```

Event hooks on PaywallView:

```swift
PaywallView()
    .onPurchaseCompleted { customerInfo in ... }
    .onPurchaseCancelled { ... }
    .onRestoreCompleted { customerInfo in ... }
    .onPurchaseFailure { error in ... }
```

---

## Manual purchase UI (without PaywallView)

```swift
struct ManualPaywallView: View {
    @State private var offering: Offering?

    var body: some View {
        VStack {
            ForEach(offering?.availablePackages ?? []) { package in
                Button(package.storeProduct.localizedTitle) {
                    Task {
                        try await Purchases.shared.purchase(package: package)
                    }
                }
            }
        }
        .task {
            offering = try? await Purchases.shared.offerings().current
        }
    }
}
```

---

## Restore purchases

Always provide a restore button — required by App Store guidelines:

```swift
try await Purchases.shared.restorePurchases()
```

---

## Sandbox testing

- Use a Sandbox Apple ID (App Store Connect → Users and Access → Sandbox Testers)
- Builds run from Xcode hit the sandbox automatically
- Subscriptions renew every few minutes in sandbox

---

## Gotchas

- Never hardcode product IDs in entitlement checks — check `entitlements.active["key"]`, not product IDs
- Always check `isActive` on the entitlement, not just presence
- StoreKit 2 is the default for new RevenueCat projects — no extra config needed
- Observer mode: if you process transactions yourself, enable observer mode so RevenueCat stays in sync
