FROM eclipse-temurin:17-jdk AS build
WORKDIR /build
COPY src/main/java/poc/ src/poc/
RUN javac --release 17 -d classes src/poc/*.java

FROM eclipse-temurin:17-jre
WORKDIR /app
COPY --from=build /build/classes/ classes/
ENV APP_BIND=0.0.0.0
ENTRYPOINT ["java", "-cp", "classes"]
CMD ["poc.Main"]
