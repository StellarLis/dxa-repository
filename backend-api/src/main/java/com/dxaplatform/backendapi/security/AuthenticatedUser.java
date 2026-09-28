package com.dxaplatform.backendapi.security;

import com.dxaplatform.backendapi.entity.Role;

import java.util.UUID;

/**
 * Кладётся в SecurityContext как principal после успешной проверки JWT --
 * все данные берутся прямо из claims токена, БЕЗ похода в базу на каждый
 * запрос (стандартная практика для stateless JWT: токен самодостаточен).
 * Доступен в контроллерах через @AuthenticationPrincipal AuthenticatedUser user.
 */
public record AuthenticatedUser(UUID id, String email, Role role) {
}
