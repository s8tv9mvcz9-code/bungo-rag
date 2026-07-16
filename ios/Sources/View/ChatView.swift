import SwiftUI

private let welcomeExamples = [
    "「今日はいい天気ですね」を旧字旧仮名に変換して",
    "「秋の夕暮れ」というテーマで文語体の文章を書いて",
    "「桜が散った。風が吹いた。」を格調高い文体に",
    "旧字旧仮名とはどういうものか教えて",
]

struct ChatView: View {
    @StateObject private var viewModel = ChatViewModel()
    @State private var inputText = ""

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                List {
                    if viewModel.messages.isEmpty && viewModel.streaming == nil {
                        Section("はじめる") {
                            ForEach(welcomeExamples, id: \.self) { example in
                                Button(example) {
                                    viewModel.send(example)
                                }
                            }
                        }
                    }

                    ForEach(Array(viewModel.messages.enumerated()), id: \.offset) { _, message in
                        MessageBubble(message: message)
                    }

                    if let streaming = viewModel.streaming {
                        MessageBubble(
                            message: ChatMessage(role: "assistant", content: streaming + " ▌")
                        )
                    }

                    if let palette = viewModel.palette {
                        PaletteBar(palette: palette)
                            .listRowSeparator(.hidden)
                    }

                    if !viewModel.sources.isEmpty {
                        DisclosureGroup("📚 参照した青空文庫テキスト（\(viewModel.sources.count) 件）") {
                            ForEach(viewModel.sources) { source in
                                VStack(alignment: .leading, spacing: 4) {
                                    HStack(spacing: 6) {
                                        // 共感覚: 手本の色点（旧サーバでは color=nil → 表示なし）
                                        if let hex = source.color, let dot = Color(bungoHex: hex) {
                                            Circle().fill(dot).frame(width: 10, height: 10)
                                        }
                                        Text("\(source.title) / \(source.author)（\(source.style)）"
                                             + (source.colorName.map { "〔\($0)〕" } ?? ""))
                                            .font(.subheadline).bold()
                                    }
                                    Text(source.text)
                                        .font(.caption)
                                        .foregroundStyle(.secondary)
                                }
                                .padding(.vertical, 4)
                            }
                        }
                    }
                }
                .listStyle(.plain)

                if let errorText = viewModel.errorText {
                    Text("⚠️ \(errorText)")
                        .font(.footnote)
                        .foregroundStyle(.red)
                        .padding(.horizontal)
                }

                HStack {
                    TextField("依頼を入力してください（例：「月夜の情景を文語体で」）", text: $inputText)
                        .textFieldStyle(.roundedBorder)
                        .onSubmit { submit() }

                    Button {
                        submit()
                    } label: {
                        if viewModel.isLoading {
                            ProgressView()
                        } else {
                            Image(systemName: "paperplane.fill")
                        }
                    }
                    .disabled(inputText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || viewModel.isLoading)
                }
                .padding()
            }
            .navigationTitle("📖 文語作文支援")
        }
    }

    private func submit() {
        let text = inputText
        inputText = ""
        viewModel.send(text)
    }
}

/// 共感覚の色帯: 入力色 → 連想色 → 手本色 のグラデーションと伝統色名
private struct PaletteBar: View {
    let palette: Palette

    var body: some View {
        let colors = palette.stops.compactMap { Color(bungoHex: $0) }
        VStack(alignment: .leading, spacing: 4) {
            if colors.count >= 2 {
                LinearGradient(colors: colors, startPoint: .leading, endPoint: .trailing)
                    .frame(height: 8)
                    .clipShape(Capsule())
            }
            Text("情調 「\(palette.blend?.name ?? "")」"
                 + ((palette.categories?.isEmpty == false)
                    ? "　—　\(palette.categories!.joined(separator: "・"))の氣配" : ""))
                .font(.caption)
                .foregroundStyle(.secondary)
        }
    }
}

/// "#RRGGBB" → SwiftUI Color（不正値は nil）
private extension Color {
    init?(bungoHex hex: String) {
        var value = hex
        if value.hasPrefix("#") { value.removeFirst() }
        guard value.count == 6, let rgb = UInt64(value, radix: 16) else { return nil }
        self.init(
            red: Double((rgb >> 16) & 0xFF) / 255.0,
            green: Double((rgb >> 8) & 0xFF) / 255.0,
            blue: Double(rgb & 0xFF) / 255.0
        )
    }
}

private struct MessageBubble: View {
    let message: ChatMessage

    private var isUser: Bool { message.role == "user" }

    var body: some View {
        HStack {
            if isUser { Spacer(minLength: 40) }
            Text(message.content)
                .padding(10)
                .background(isUser ? Color.accentColor.opacity(0.2) : Color.gray.opacity(0.15))
                .cornerRadius(12)
            if !isUser { Spacer(minLength: 40) }
        }
        .listRowSeparator(.hidden)
    }
}

#Preview {
    ChatView()
}
