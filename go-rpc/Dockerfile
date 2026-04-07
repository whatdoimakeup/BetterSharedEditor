FROM golang:1.21-alpine AS builder

WORKDIR /app
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -o /go-rpc .

FROM alpine:3.18

COPY --from=builder /go-rpc /go-rpc
EXPOSE 8002
CMD ["/go-rpc"]
