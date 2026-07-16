import Foundation

enum Config {
    /// Info.plist の BUNGO_BASE_URL（XcodeGen が project.yml から注入）を読み込む。
    /// 万一未設定でも本番 bungo-api の URL にフォールバックする。
    static var baseURL: URL {
        let fallback = "https://bungo-api.gentleground-ba3d7ba2.japaneast.azurecontainerapps.io"
        let value = (Bundle.main.object(forInfoDictionaryKey: "BUNGO_BASE_URL") as? String) ?? fallback
        return URL(string: value) ?? URL(string: fallback)!
    }

    /// Info.plist の BUNGO_API_KEY（関係者用の任意キー）。空/未設定なら nil = 公開枠。
    /// 関係者向けビルドでのみ project.yml に値を入れて再生成する（公開配布は空）。
    static var apiKey: String? {
        let value = Bundle.main.object(forInfoDictionaryKey: "BUNGO_API_KEY") as? String
        return (value?.isEmpty == false) ? value : nil
    }
}
