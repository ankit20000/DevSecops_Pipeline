FROM eclipse-temurin:17-jdk

WORKDIR /home/petclinic/

COPY ./target/spring-petclinic-3.2.0-SNAPSHOT.jar .

EXPOSE 8080

ENV MYSQL_URL=jdbc:mysql://petclinic-mysql:3306/petclinic

CMD ["java", "-jar", "spring-petclinic-3.2.0-SNAPSHOT.jar"]

