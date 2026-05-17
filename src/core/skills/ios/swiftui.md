> SwiftUI app development for iOS — Xcode setup, architecture, navigation, state management, App Store.

# Apple SwiftUI App Development

## Agent hints
- **Output path:** `generated/apps/ios/<AppName>/` for new apps built from scratch · `apps/ios/<AppName>/` only when modifying an existing app already in that directory
- **Preferred thinking:** coding → `medium`, research → `low`
- **Commonly related skills:** [revenue-cat.md](revenue-cat.md) for any payments or subscriptions

## Xcode project setup

**New project:** File → New → Project → App. Choose SwiftUI interface, Swift language.

**Workspace vs project:** Use a `.xcworkspace` only when you have multiple `.xcodeproj` files (e.g. CocoaPods). For SPM-only projects, stay with `.xcodeproj`.

**Folder structure:**
```
MyApp/
  MyApp.xcodeproj
  MyApp/
    MyAppApp.swift      # @main entry point
    ContentView.swift
    Features/
      FeatureName/
        FeatureView.swift
        FeatureViewModel.swift
    Models/
    Services/
    Resources/           # assets, localizations
  MyAppTests/
  MyAppUITests/
```

**Targets:** One app target per platform variant (iOS, macOS). Share code via local SPM packages or a Framework target.

**Signing:** Xcode → Target → Signing & Capabilities → enable "Automatically manage signing". Select your team.

**Capabilities:** Add via Target → Signing & Capabilities → "+ Capability". Common: In-App Purchase, Push Notifications, iCloud.

**Minimum deployment target:** iOS 17+ recommended for `@Observable`. iOS 16+ for `NavigationStack`.

---

## Dependencies (SPM)

File → Add Package Dependencies → paste repo URL. Prefer SPM over CocoaPods for new projects.

---

## Architecture

### App entry point

```swift
@main
struct MyApp: App {
    var body: some Scene {
        WindowGroup {
            ContentView()
        }
    }
}
```

### State management

Use `@Observable` (iOS 17+) for ViewModels — no `@Published` needed:

```swift
@Observable
final class HomeViewModel {
    var items: [Item] = []
    var isLoading = false

    func load() async {
        isLoading = true
        items = try await service.fetchItems()
        isLoading = false
    }
}
```

Instantiate in the view that owns it with `@State`:

```swift
struct HomeView: View {
    @State private var vm = HomeViewModel()

    var body: some View {
        List(vm.items) { ... }
            .task { await vm.load() }
    }
}
```

Pass down to children via `@Environment` or direct property:

```swift
// parent
ContentView().environment(vm)

// child
struct ChildView: View {
    @Environment(HomeViewModel.self) var vm
}
```

For iOS 16 compatibility use `ObservableObject` + `@StateObject` / `@ObservedObject`.

### Navigation

```swift
// Root
NavigationStack(path: $router.path) {
    HomeView()
        .navigationDestination(for: Route.self) { route in
            switch route {
            case .detail(let id): DetailView(id: id)
            case .settings:       SettingsView()
            }
        }
}

// Push
router.path.append(Route.detail(id: item.id))

// Pop to root
router.path = NavigationPath()
```

Centralise routing in an `@Observable` Router injected via `@Environment`.

---

## Key SwiftUI patterns

```swift
// Async work tied to view lifecycle
.task { await vm.load() }

// Conditional sheets
.sheet(isPresented: $showPaywall) { PaywallView() }

// Environment values
.environment(\.colorScheme, .dark)

// Preference keys for child→parent communication (use sparingly)
```

**Avoid:** `DispatchQueue.main.async` inside views — use `.task` and `@MainActor`. Don't use `NavigationView` (deprecated iOS 16+).

---

## Testing

```swift
// Swift Testing (Xcode 16+, recommended)
import Testing

@Test func itemLoads() async throws {
    let vm = HomeViewModel(service: MockService())
    await vm.load()
    #expect(vm.items.count == 3)
}

// XCTest still works fine for UI tests
```

---

## App Store submission

1. Set version + build number in target → General
2. Archive: Product → Archive
3. Distribute via Xcode Organizer → App Store Connect
4. Fill in metadata, screenshots, privacy labels in App Store Connect

---

## Payments & subscriptions

> For anything involving in-app purchases or subscriptions, see [revenue-cat.md](revenue-cat.md).
