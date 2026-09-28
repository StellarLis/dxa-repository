package com.dxaplatform.backendapi.security;

import com.dxaplatform.backendapi.entity.Role;
import io.jsonwebtoken.Claims;
import io.jsonwebtoken.JwtException;
import io.jsonwebtoken.Jwts;
import io.jsonwebtoken.security.Keys;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import javax.crypto.SecretKey;
import java.nio.charset.StandardCharsets;
import java.util.Date;
import java.util.UUID;

@Service
public class JwtService {

    private final SecretKey secretKey;
    private final long expirySeconds;

    public JwtService(
            @Value("${app.jwt.secret}") String secret,
            @Value("${app.jwt.expiry-seconds}") long expirySeconds
    ) {
        // HS256 требует ключ длиной не менее 256 бит -- значение по умолчанию
        // в application.yml подобрано так, чтобы это условие выполнялось;
        // в проде секрет ОБЯЗАТЕЛЬНО переопределяется переменной окружения JWT_SECRET
        this.secretKey = Keys.hmacShaKeyFor(secret.getBytes(StandardCharsets.UTF_8));
        this.expirySeconds = expirySeconds;
    }

    public String generateToken(UUID userId, String email, Role role) {
        Date now = new Date();
        Date expiry = new Date(now.getTime() + expirySeconds * 1000);

        return Jwts.builder()
                .subject(userId.toString())
                .claim("email", email)
                .claim("role", role.name())
                .issuedAt(now)
                .expiration(expiry)
                .signWith(secretKey)
                .compact();
    }

    /** Бросает JwtException (истёк срок, неверная подпись и т.п.) -- ловится в фильтре. */
    public Claims parseClaims(String token) throws JwtException {
        return Jwts.parser()
                .verifyWith(secretKey)
                .build()
                .parseSignedClaims(token)
                .getPayload();
    }

    public AuthenticatedUser toAuthenticatedUser(Claims claims) {
        UUID id = UUID.fromString(claims.getSubject());
        String email = claims.get("email", String.class);
        Role role = Role.valueOf(claims.get("role", String.class));
        return new AuthenticatedUser(id, email, role);
    }

    public long getExpirySeconds() {
        return expirySeconds;
    }
}
