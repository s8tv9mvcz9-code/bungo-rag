import Foundation

enum Config {
    /// Info.plist の BUNGO_BASE_URL（XcodeGen が project.yml から注入）を読み込む。
    /// 万一未設定でも本番 bungo-api の URL にフォールバックする。
    static var baseURL: URL {
        let fallback = "https://bungo-api.gentleground-ba3d7ba2.japaneast.azurecontainerapps.io"
        let value = (Bundle.main.object(forInfoDictionaryKey: "BUNGO_BASE_URL") as? String) ?? fallback
        return URL(string: value) ?? URL(string: fallback)!
    }
}
