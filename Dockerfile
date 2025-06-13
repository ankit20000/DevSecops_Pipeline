# Use OpenJDK base image
FROM openjdk:17-jdk-slim

# Set working directory
WORKDIR /app

# Copy the built JAR file into the image
COPY target/spring-petclinic-3.2.0-SNAPSHOT.jar app.jar

# Expose the application port (Spring Boot default)
EXPOSE 8081

# Run the application
ENTRYPOINT ["java", "-jar", "app.jar"]

