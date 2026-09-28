import SwiftUI

private struct FixtureRecord: Identifiable {
    let name: String
    let section: String
    let status: String
    let tab: String
    let group: String

    var id: String { name }
}

private let records = [
    FixtureRecord(name: "Quartz", section: "Research", status: "Ready", tab: "Pending", group: "Alpha"),
    FixtureRecord(name: "Cedar", section: "Operations", status: "Active", tab: "Archive", group: "Beta"),
    FixtureRecord(name: "Nimbus", section: "Design", status: "Review", tab: "Current", group: "Gamma"),
    FixtureRecord(name: "Orchid", section: "Reports", status: "Hold", tab: "Later", group: "Delta"),
]

private let longTreeRecords: [FixtureRecord] = {
    var values = (1...36).map { number in
        FixtureRecord(name: String(format: "Request %02d", number),
                      section: records[(number - 1) % records.count].section,
                      status: records[((number - 1) / records.count) % records.count].status,
                      tab: "", group: "")
    }
    values.insert(records[0], at: 25)
    return values
}()

private enum FixtureCategory: String {
    case navigation
    case search
    case filter
    case tabs
    case expand
    case duplicate_label
    case stale_index
    case missing_target
    case recovery
    case dialog
    case long_tree
}

private struct FixtureCase {
    let id: String
    let category: FixtureCategory
    let variant: Int

    static func parse(_ raw: String) -> FixtureCase? {
        let parts = raw.split(separator: "-")
        guard parts.count == 3,
              parts[0] == "native",
              let category = FixtureCategory(rawValue: String(parts[1])),
              let variant = Int(parts[2]),
              (category == .long_tree ? variant == 0 : (0...3).contains(variant)) else { return nil }
        return FixtureCase(id: raw, category: category, variant: variant)
    }

    var target: FixtureRecord { records[variant] }

    var goal: String {
        switch category {
        case .navigation: return "Open the \(target.section) section, then open \(target.name)."
        case .search: return "Search for \(target.name), then open its record."
        case .filter: return "Set status to \(target.status), then open \(target.name)."
        case .tabs: return "Choose the \(target.tab) tab, then open \(target.name)."
        case .expand: return "Expand \(target.group), then open \(target.name)."
        case .duplicate_label: return "Use the Open button in the \(target.name) row."
        case .stale_index: return "Reorder the list, then use the Open button in the \(target.name) row."
        case .missing_target: return "Refresh state to reveal \(target.name), then open it."
        case .recovery: return "Search for \(target.name); after the first empty result, retry and open it."
        case .dialog: return "Open the picker and select \(target.name) in the dialog."
        case .long_tree: return "Choose the \(target.section) queue and \(target.status) status, then use Open in the \(target.name) row."
        }
    }
}

private struct FixtureView: View {
    @State private var caseID: String
    @State private var caseInput: String
    @State private var selectedSection: String? = nil
    @State private var query = ""
    @State private var submittedQuery = ""
    @State private var statusFilter = "All"
    @State private var selectedTab = ""
    @State private var expandedGroup: String? = nil
    @State private var reordered = false
    @State private var revealed = false
    @State private var firstSearch = false
    @State private var retried = false
    @State private var pickerOpen = false
    @State private var completed = false
    @State private var mistakes = 0
    @State private var message = "Task incomplete"

    init() {
        let args = ProcessInfo.processInfo.arguments
        let requested: String
        if let index = args.firstIndex(of: "--case-id"), args.indices.contains(index + 1) {
            requested = args[index + 1]
        } else {
            requested = "native-navigation-0"
        }
        let initial = FixtureCase.parse(requested) == nil ? "native-navigation-0" : requested
        let initialVariant = FixtureCase.parse(initial)?.variant ?? 0
        _caseID = State(initialValue: initial)
        _caseInput = State(initialValue: initial)
        _selectedTab = State(initialValue: records[(initialVariant + 1) % records.count].tab)
    }

    private var task: FixtureCase? { FixtureCase.parse(caseID) }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Computer Use Native Fixture").font(.title2).bold()
            Text("Synthetic records for repeatable UI tasks.").foregroundStyle(.secondary)
            HStack {
                TextField("Case ID", text: $caseInput)
                    .textFieldStyle(.roundedBorder)
                    .accessibilityLabel("Case ID")
                Button("Load case") { loadCase() }
            }
            if let task {
                Text("Case ID: \(task.id)")
                Text("Goal: \(task.goal)").fontWeight(.semibold)
                Divider()
                ScrollView {
                    scenario(task)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                .frame(maxHeight: .infinity)
                Divider()
                Text(completed ? "PASS \(task.id)" : message)
                    .fontWeight(completed ? .bold : .regular)
                    .foregroundStyle(completed ? .green : .primary)
                    .accessibilityIdentifier("fixture-result")
                Text("Wrong actions: \(mistakes)")
            } else {
                Text("Invalid case ID. Use native-<category>-<0..3>; long_tree uses variant 0 only.")
            }
        }
        .padding(20)
        .frame(minWidth: 650, minHeight: 520)
        .sheet(isPresented: $pickerOpen) {
            VStack(alignment: .leading, spacing: 12) {
                Text("Select a record").font(.headline)
                ForEach(records) { record in
                    recordRow(record, identicalButton: true, closeOnSuccess: true)
                }
                Button("Close picker") { pickerOpen = false }
            }
            .padding(20)
            .frame(minWidth: 420)
        }
    }

    private func loadCase() {
        caseID = caseInput.trimmingCharacters(in: .whitespacesAndNewlines)
        selectedSection = nil
        query = ""
        submittedQuery = ""
        statusFilter = "All"
        if let next = FixtureCase.parse(caseID) {
            selectedTab = records[(next.variant + 1) % records.count].tab
        }
        expandedGroup = nil
        reordered = false
        revealed = false
        firstSearch = false
        retried = false
        pickerOpen = false
        completed = false
        mistakes = 0
        message = "Task incomplete"
    }

    private func openRecord(_ record: FixtureRecord, allowed: Bool = true, closeOnSuccess: Bool = false) {
        guard let task else { return }
        if record.name == task.target.name && allowed {
            completed = true
            message = ""
            if closeOnSuccess { pickerOpen = false }
        } else {
            mistakes += 1
            message = "Opened \(record.name) before reaching the requested state."
        }
    }

    private func recordRow(_ record: FixtureRecord, identicalButton: Bool = false,
                           allowed: Bool = true, closeOnSuccess: Bool = false,
                           enabled: Bool = true) -> some View {
        HStack {
            VStack(alignment: .leading) {
                Text(record.name).fontWeight(.semibold)
                Text("\(record.section) · \(record.status)").font(.caption).foregroundStyle(.secondary)
            }
            Spacer()
            Button(identicalButton ? "Open" : "Open \(record.name)") {
                openRecord(record, allowed: allowed, closeOnSuccess: closeOnSuccess)
            }
            .disabled(!enabled)
        }
        .padding(.vertical, 5)
    }

    @ViewBuilder
    private func scenario(_ task: FixtureCase) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(task.category.rawValue.replacingOccurrences(of: "_", with: " ").capitalized)
                .font(.headline)

            switch task.category {
            case .navigation:
                HStack {
                    ForEach(records) { record in
                        Button(record.section) { selectedSection = record.section }
                    }
                }
                if let record = records.first(where: { $0.section == selectedSection }) {
                    recordRow(record, allowed: selectedSection == task.target.section)
                } else {
                    Text("Choose a section.")
                }

            case .search:
                searchControls(recovery: false, target: task.target)
                let found = records.filter {
                    !submittedQuery.isEmpty && $0.name.localizedCaseInsensitiveContains(submittedQuery)
                }
                if found.isEmpty {
                    Text(submittedQuery.isEmpty ? "Enter a name and select Search." : "No results.")
                }
                ForEach(found) { record in recordRow(record) }

            case .filter:
                Picker("Status", selection: $statusFilter) {
                    Text("All").tag("All")
                    ForEach(records) { record in Text(record.status).tag(record.status) }
                }
                .frame(maxWidth: 280)
                ForEach(records.filter { statusFilter == "All" || $0.status == statusFilter }) { record in
                    recordRow(record, allowed: statusFilter == task.target.status)
                }

            case .tabs:
                HStack {
                    ForEach(records) { record in
                        Button(record.tab) { selectedTab = record.tab }
                    }
                }
                if let record = records.first(where: { $0.tab == selectedTab }) {
                    recordRow(record, allowed: selectedTab == task.target.tab)
                }

            case .expand:
                ForEach(records) { record in
                    Button("\(expandedGroup == record.group ? "Collapse" : "Expand") \(record.group)") {
                        expandedGroup = expandedGroup == record.group ? nil : record.group
                    }
                    if expandedGroup == record.group {
                        recordRow(record, allowed: expandedGroup == task.target.group)
                    }
                }

            case .duplicate_label:
                ForEach(records) { record in recordRow(record, identicalButton: true) }

            case .stale_index:
                Button("Reorder list") { reordered = true }
                let order = reordered ? [2, 0, 3, 1] : [0, 1, 2, 3]
                ForEach(order, id: \.self) { index in
                    recordRow(records[index], identicalButton: true, allowed: reordered)
                }

            case .missing_target:
                Button("Refresh state") { revealed = true }
                ForEach(records.filter { revealed || $0.name != task.target.name }) { record in
                    recordRow(record, allowed: revealed)
                }

            case .recovery:
                searchControls(recovery: true, target: task.target)
                if firstSearch && !retried {
                    Text("No results. The index is stale.")
                    Button("Retry search") {
                        retried = true
                        message = "Results refreshed."
                    }
                } else if retried {
                    recordRow(task.target, allowed: firstSearch && retried)
                } else {
                    Text("Search for the requested record.")
                }

            case .dialog:
                Button("Open picker") { pickerOpen = true }

            case .long_tree:
                Text("Selected queue: \(selectedSection ?? "None")")
                HStack {
                    ForEach(records) { record in
                        Button(record.section) { selectedSection = record.section }
                            .accessibilityValue(selectedSection == record.section ? "Selected" : "Not selected")
                    }
                }
                Picker("Status", selection: $statusFilter) {
                    Text("All").tag("All")
                    ForEach(records) { record in Text(record.status).tag(record.status) }
                }
                .frame(maxWidth: 280)
                ForEach(orderedLongTreeRecords(), id: \.id) { record in
                    let ready = selectedSection == task.target.section && statusFilter == task.target.status
                    recordRow(record, identicalButton: true, allowed: ready,
                              enabled: record.name != task.target.name || ready)
                }
            }
        }
    }

    private func orderedLongTreeRecords() -> [FixtureRecord] {
        func rank(_ record: FixtureRecord) -> Int {
            (selectedSection != nil && record.section == selectedSection ? 1 : 0) +
            (statusFilter != "All" && record.status == statusFilter ? 1 : 0)
        }
        return longTreeRecords.enumerated().sorted { left, right in
            let difference = rank(left.element) - rank(right.element)
            return difference == 0 ? left.offset < right.offset : difference > 0
        }.map(\.element)
    }

    private func searchControls(recovery: Bool, target: FixtureRecord) -> some View {
        HStack {
            TextField("Record name", text: $query)
                .textFieldStyle(.roundedBorder)
                .accessibilityLabel("Record name")
            Button("Search") {
                submittedQuery = query.trimmingCharacters(in: .whitespacesAndNewlines)
                if recovery {
                    firstSearch = submittedQuery.caseInsensitiveCompare(target.name) == .orderedSame
                    retried = false
                    message = firstSearch ? "No results. Retry search." : "No results for that name."
                }
            }
        }
    }
}

@main
private struct JevCUFixtureApp: App {
    var body: some Scene {
        WindowGroup("Computer Use Native Fixture") {
            FixtureView()
        }
    }
}
