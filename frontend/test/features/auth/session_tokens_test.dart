import 'dart:async';

import 'package:flutter_test/flutter_test.dart';
import 'package:nxtrep/core/storage/refresh_token_store.dart';
import 'package:nxtrep/features/auth/domain/auth_models.dart';
import 'package:nxtrep/features/auth/domain/session_tokens.dart';

class _ControlledStore implements RefreshTokenStore {
  final writeStarted = Completer<void>();
  final allowWrite = Completer<void>();
  String? value;

  @override
  Future<void> delete() async => value = null;

  @override
  Future<String?> read() async => value;

  @override
  Future<void> write(String token) async {
    writeStarted.complete();
    await allowWrite.future;
    value = token;
  }
}

const _pair = TokenPair(
  accessToken: 'access',
  refreshToken: 'refresh',
  tokenType: 'bearer',
  expiresIn: 900,
  refreshExpiresIn: 86400,
  user: AuthUser(
    id: '00000000-0000-0000-0000-000000000001',
    username: 'tester',
    passwordSetupRequired: false,
  ),
);

void main() {
  test('persists rotated refresh token before exposing access token', () async {
    final store = _ControlledStore();
    final tokens = SessionTokens(store);

    final replace = tokens.replace(_pair);
    await store.writeStarted.future;
    expect(tokens.accessToken, isNull);
    expect(tokens.refreshToken, isNull);

    store.allowWrite.complete();
    await replace;
    expect(tokens.accessToken, 'access');
    expect(tokens.refreshToken, 'refresh');
    expect(store.value, 'refresh');
  });
}
