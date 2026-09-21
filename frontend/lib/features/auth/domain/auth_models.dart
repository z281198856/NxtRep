class AuthUser {
  const AuthUser({
    required this.id,
    required this.username,
    required this.passwordSetupRequired,
  });

  factory AuthUser.fromJson(Map<String, dynamic> json) => AuthUser(
    id: json['id'] as String,
    username: json['username'] as String,
    passwordSetupRequired: json['password_setup_required'] as bool,
  );

  final String id;
  final String username;
  final bool passwordSetupRequired;
}

class TokenPair {
  const TokenPair({
    required this.accessToken,
    required this.refreshToken,
    required this.tokenType,
    required this.expiresIn,
    required this.refreshExpiresIn,
    required this.user,
  });

  factory TokenPair.fromJson(Map<String, dynamic> json) => TokenPair(
    accessToken: json['access_token'] as String,
    refreshToken: json['refresh_token'] as String,
    tokenType: json['token_type'] as String,
    expiresIn: json['expires_in'] as int,
    refreshExpiresIn: json['refresh_expires_in'] as int,
    user: AuthUser.fromJson(json['user'] as Map<String, dynamic>),
  );

  final String accessToken;
  final String refreshToken;
  final String tokenType;
  final int expiresIn;
  final int refreshExpiresIn;
  final AuthUser user;
}

class CurrentAccount {
  const CurrentAccount({
    required this.id,
    required this.username,
    required this.status,
    required this.isAdmin,
    required this.passwordSetupRequired,
    required this.profileInitialized,
  });

  factory CurrentAccount.fromJson(Map<String, dynamic> json) => CurrentAccount(
    id: json['id'] as String,
    username: json['username'] as String,
    status: json['status'] as String,
    isAdmin: json['is_admin'] as bool,
    passwordSetupRequired: json['password_setup_required'] as bool,
    profileInitialized: json['profile_initialized'] as bool,
  );

  final String id;
  final String username;
  final String status;
  final bool isAdmin;
  final bool passwordSetupRequired;
  final bool profileInitialized;
}
