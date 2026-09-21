import '../../../core/storage/refresh_token_store.dart';
import 'auth_models.dart';

class SessionTokens {
  SessionTokens(this._refreshTokenStore);

  final RefreshTokenStore _refreshTokenStore;

  String? _accessToken;
  String? _refreshToken;

  String? get accessToken => _accessToken;
  String? get refreshToken => _refreshToken;

  Future<String?> loadRefreshToken() async {
    _refreshToken ??= await _refreshTokenStore.read();
    return _refreshToken;
  }

  Future<void> replace(TokenPair pair) async {
    // The rotated refresh token is persisted before exposing the new access
    // token, so requests can never proceed with a token pair that was not saved.
    await _refreshTokenStore.write(pair.refreshToken);
    _refreshToken = pair.refreshToken;
    _accessToken = pair.accessToken;
  }

  Future<void> clear() async {
    _accessToken = null;
    _refreshToken = null;
    await _refreshTokenStore.delete();
  }
}
