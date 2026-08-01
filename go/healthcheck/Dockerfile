FROM golang:1.22 AS build
WORKDIR /src
COPY go.mod ./
COPY *.go ./
RUN CGO_ENABLED=0 go build -o /healthcheck .

FROM gcr.io/distroless/static-debian12
COPY --from=build /healthcheck /healthcheck
COPY devices.json /devices.json
ENV INVENTORY_FILE=/devices.json
EXPOSE 9200
ENTRYPOINT ["/healthcheck"]
