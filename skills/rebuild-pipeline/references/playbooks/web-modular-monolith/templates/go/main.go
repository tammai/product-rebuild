package main

import (
	"log"
	"net/http"

	"github.com/gin-gonic/gin"
)

func newRouter() *gin.Engine {
	r := gin.New()
	r.Use(gin.Recovery())
	r.GET("/healthz", func(c *gin.Context) { c.JSON(http.StatusOK, gin.H{"status": "ok"}) })
	return r
}

func main() {
	if err := newRouter().Run(":8080"); err != nil {
		log.Fatal(err)
	}
}
