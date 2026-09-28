FROM eclipse-temurin:21-jdk AS build

WORKDIR /workspace
COPY . .

RUN chmod +x ./gradlew \
    && ./gradlew bootJar --no-daemon \
    && find build/libs -maxdepth 1 -type f -name '*.jar' ! -name '*-plain.jar' -exec cp {} /workspace/app.jar \;

FROM eclipse-temurin:21-jre

WORKDIR /app
COPY --from=build /workspace/app.jar ./app.jar

ENTRYPOINT ["java", "-jar", "/app/app.jar"]