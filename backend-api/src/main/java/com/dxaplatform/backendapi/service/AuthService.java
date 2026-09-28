package com.dxaplatform.backendapi.service;

import com.dxaplatform.backendapi.dto.AuthResponse;
import com.dxaplatform.backendapi.dto.LoginRequest;
import com.dxaplatform.backendapi.dto.RegisterRequest;
import com.dxaplatform.backendapi.entity.Role;
import com.dxaplatform.backendapi.entity.User;
import com.dxaplatform.backendapi.exception.ApiException;
import com.dxaplatform.backendapi.repository.UserRepository;
import com.dxaplatform.backendapi.security.JwtService;
import org.springframework.http.HttpStatus;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class AuthService {

    private final UserRepository userRepository;
    private final PasswordEncoder passwordEncoder;
    private final JwtService jwtService;

    public AuthService(UserRepository userRepository, PasswordEncoder passwordEncoder, JwtService jwtService) {
        this.userRepository = userRepository;
        this.passwordEncoder = passwordEncoder;
        this.jwtService = jwtService;
    }

    @Transactional
    public AuthResponse register(RegisterRequest request) {
        if (userRepository.existsByEmail(request.email())) {
            throw new ApiException(HttpStatus.CONFLICT, "Пользователь с таким email уже зарегистрирован");
        }

        User user = User.builder()
                .email(request.email())
                .passwordHash(passwordEncoder.encode(request.password()))
                .displayName(request.displayName())
                .role(Role.USER)
                .build();
        userRepository.save(user);

        String token = jwtService.generateToken(user.getId(), user.getEmail(), user.getRole());
        return AuthResponse.bearer(token, jwtService.getExpirySeconds());
    }

    public AuthResponse login(LoginRequest request) {
        User user = userRepository.findByEmail(request.email())
                // намеренно одно и то же сообщение и для "нет такого email", и для
                // "неверный пароль" -- не даём атакующему понять, какой из двух случаев
                .orElseThrow(() -> new ApiException(HttpStatus.UNAUTHORIZED, "Неверный email или пароль"));

        if (!passwordEncoder.matches(request.password(), user.getPasswordHash())) {
            throw new ApiException(HttpStatus.UNAUTHORIZED, "Неверный email или пароль");
        }

        String token = jwtService.generateToken(user.getId(), user.getEmail(), user.getRole());
        return AuthResponse.bearer(token, jwtService.getExpirySeconds());
    }
}
