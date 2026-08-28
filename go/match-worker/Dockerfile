FROM golang:1.23-alpine AS build

WORKDIR /src
COPY go.mod ./
RUN go mod download
COPY . .
RUN go build -o /out/match-worker ./cmd/match-worker

FROM alpine:3.20
COPY --from=build /out/match-worker /usr/local/bin/match-worker
USER 65532:65532
ENTRYPOINT ["match-worker"]
