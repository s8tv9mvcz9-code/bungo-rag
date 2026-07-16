import Combine
import Foundation

@MainActor
final class ChatViewModel: ObservableObject {
    @Published var messages: [ChatMessage] = []
    @Published var streaming: String? = nil
    @Published var sources: [Source] = []
    @Published var palette: Palette? = nil   // 共感覚パレット（情調→伝統色）
    @Published var isLoading: Bool = false
    @Published var errorText: String? = nil

    private let api = BungoAPI(baseURL: Config.baseURL, apiKey: Config.apiKey)

    func send(_ text: String) {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, !isLoading else { return }

        let history = messages
        messages.append(ChatMessage(role: "user", content: trimmed))
        streaming = ""
        sources = []
        palette = nil
        errorText = nil
        isLoading = true

        Task {
            do {
                try await api.streamChat(
                    ChatRequest(message: trimmed, history: history, topK: 5)
                ) { [weak self] event in
                    guard let self else { return }
                    switch event {
                    case .token(let content):
                        self.streaming = (self.streaming ?? "") + content
                    case .sources(let newSources, let newPalette):
                        self.sources = newSources
                        self.palette = newPalette
                    case .done:
                        if let finalText = self.streaming {
                            self.messages.append(ChatMessage(role: "assistant", content: finalText))
                        }
                        self.streaming = nil
                        self.isLoading = false
                    case .error(let message):
                        self.errorText = message
                        self.streaming = nil
                        self.isLoading = false
                    }
                }
            } catch {
                self.errorText = "通信エラー: \(error.localizedDescription)"
                self.streaming = nil
                self.isLoading = false
            }
        }
    }
}
